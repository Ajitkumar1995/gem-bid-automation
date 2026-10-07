import tempfile
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from datetime import timedelta
from django.test import TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.db import connection, close_old_connections
from django.urls import reverse
from concurrent.futures import ThreadPoolExecutor
from django.test import SimpleTestCase
from rest_framework.test import APIClient
from unittest.mock import patch

from apps.documents.models import LinkedDocument
from apps.generation.models import BidPreparation, GeneratedDocument
from apps.companies.models import CompanyDocument, CompanyProfile
from .limits import get_active_bid_count, get_effective_bid_limit
from .models import Bid, BidLimitAudit, BidRetentionPolicy, BidSystemSettings
from services.requirements import analyze_requirements


class ApiSchemaTests(SimpleTestCase):
    def test_openapi_schema_endpoint_is_available(self):
        response = self.client.get("/api/schema/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "/api/bids/")

    def test_swagger_documentation_page_is_available(self):
        response = self.client.get("/api/docs/")

        self.assertEqual(response.status_code, 200)


class BidUploadRetentionTests(TestCase):
    def setUp(self):
        self.temp_media = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.temp_media.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(self.temp_media.cleanup)
        self.user = get_user_model().objects.create_user(username="bid-owner", password="test-password")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    @staticmethod
    def pdf_upload(filename="bid.pdf"):
        return SimpleUploadedFile(filename, b"%PDF-1.4\nminimal test pdf", content_type="application/pdf")

    @patch("apps.bids.tasks.extract_bid_pdf.delay", return_value=SimpleNamespace(id="extract-job"))
    def test_limit_blocks_second_bid_and_delete_cleans_only_bid_files(self, _delay):
        response = self.client.post("/api/bids/", {
            "title": "Original tender",
            "bid_number": "GEM/2026/B/1234567",
            "source_pdf": self.pdf_upload("original.pdf"),
        }, format="multipart")
        self.assertEqual(response.status_code, 201, response.data)
        bid = Bid.objects.get(uploaded_by=self.user)
        old_source = bid.source_pdf.name
        self.assertTrue(bid.source_pdf.storage.exists(old_source))

        BidPreparation.objects.create(bid=bid, bid_number=bid.bid_number)
        generated = GeneratedDocument.objects.create(
            bid=bid,
            document_type="test_doc",
            title="Old generated file",
            generated_by=self.user,
        )
        generated.file.save("old-generated.pdf", ContentFile(b"%PDF-1.4\nold"), save=True)
        old_generated = generated.file.name
        linked = LinkedDocument.objects.create(bid=bid, url="https://example.test/old.pdf")
        linked.file.save("old-linked.pdf", ContentFile(b"%PDF-1.4\nold linked"), save=True)
        old_linked = linked.file.name
        company = CompanyProfile.objects.create(owner=self.user, legal_name="Reusable Company")
        company_document = CompanyDocument.objects.create(company=company, title="GST certificate", document_type="gst")
        company_document.file.save("gst.pdf", ContentFile(b"permanent company evidence"), save=True)
        reusable_document_name = company_document.file.name
        bid.extracted_text = "old extracted details"
        bid.status = Bid.Status.READY
        bid.save(update_fields=["extracted_text", "status"])

        response = self.client.post("/api/bids/", {
            "title": "Updated tender",
            "bid_number": "GEM/2026/B/1234567",
            "source_pdf": self.pdf_upload("replacement.pdf"),
        }, format="multipart")

        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data["error"], "BID_LIMIT_REACHED")
        self.assertIn("maximum active bid limit of 1", response.data["message"])
        self.assertEqual(Bid.objects.filter(uploaded_by=self.user).count(), 1)
        bid.refresh_from_db()
        self.assertEqual(bid.title, "Original tender")
        self.assertEqual(bid.extracted_text, "old extracted details")
        self.assertTrue(bid.source_pdf.storage.exists(old_source))
        self.assertTrue(GeneratedDocument.objects.filter(pk=generated.pk).exists())
        self.assertTrue(LinkedDocument.objects.filter(pk=linked.pk).exists())

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.delete(f"/api/bids/{bid.pk}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Bid.objects.filter(pk=bid.pk).exists())
        self.assertFalse(GeneratedDocument.objects.filter(pk=generated.pk).exists())
        self.assertFalse(LinkedDocument.objects.filter(pk=linked.pk).exists())
        self.assertFalse(bid.source_pdf.storage.exists(old_source))
        self.assertFalse(bid.source_pdf.storage.exists(old_generated))
        self.assertFalse(bid.source_pdf.storage.exists(old_linked))
        self.assertTrue(company_document.file.storage.exists(reusable_document_name))
        self.assertTrue(CompanyDocument.objects.filter(pk=company_document.pk).exists())
        self.client.force_login(self.user)
        upload_response = self.client.post("/api/bids/", {
            "bid_number": "GEM/2026/B/7654321",
            "source_pdf": self.pdf_upload("next.pdf"),
        }, format="multipart")
        self.assertEqual(upload_response.status_code, 201, upload_response.data)

    @patch("apps.bids.tasks.extract_bid_pdf.delay", return_value=SimpleNamespace(id="extract-job"))
    def test_user_specific_bid_limit_and_slot_reuse(self, _delay):
        other_user = get_user_model().objects.create_user(username="other-bid-owner", password="test-password")
        BidRetentionPolicy.objects.create(user=self.user, bid_limit=2)
        self.assertEqual(get_effective_bid_limit(self.user), 2)
        self.assertEqual(get_effective_bid_limit(other_user), 1)

        created_ids = []
        for number in range(2):
            response = self.client.post("/api/bids/", {
                "bid_number": f"GEM/2026/B/{number + 1}",
                "source_pdf": self.pdf_upload(f"tender-{number}.pdf"),
            }, format="multipart")
            self.assertEqual(response.status_code, 201, response.data)
            created_ids.append(response.data["id"])
        self.assertEqual(get_active_bid_count(self.user), 2)

        response = self.client.post("/api/bids/", {
            "bid_number": "GEM/2026/B/3",
            "source_pdf": self.pdf_upload("tender-3.pdf"),
        }, format="multipart")
        self.assertEqual(response.status_code, 409)

        self.client.delete(f"/api/bids/{created_ids[0]}/")
        response = self.client.post("/api/bids/", {
            "bid_number": "GEM/2026/B/3",
            "source_pdf": self.pdf_upload("tender-3.pdf"),
        }, format="multipart")
        self.assertEqual(response.status_code, 201, response.data)

    def test_user_cannot_read_or_delete_another_users_bid(self):
        other_user = get_user_model().objects.create_user(username="private-bid-owner", password="test-password")
        other_bid = Bid.objects.create(uploaded_by=other_user, source_pdf=self.pdf_upload("private.pdf"))

        self.assertEqual(self.client.get(f"/api/bids/{other_bid.pk}/").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/bids/{other_bid.pk}/").status_code, 404)
        self.assertTrue(Bid.objects.filter(pk=other_bid.pk).exists())

    def test_stale_bid_links_redirect_to_dashboard_with_explanation(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("bid-link-list", args=[6]), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertRedirects(response, reverse("bid-dashboard"))
        self.assertContains(
            response,
            "That bid is no longer available. It may have been completed, deleted, or expired.",
        )

    def test_bid_links_do_not_disclose_other_users_bids(self):
        self.client.force_login(self.user)
        other_user = get_user_model().objects.create_user(username="private-links-owner")
        other_bid = Bid.objects.create(uploaded_by=other_user, source_pdf=self.pdf_upload("private-links.pdf"))

        response = self.client.get(reverse("bid-link-list", args=[other_bid.pk]), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "That bid is no longer available.")

    def test_null_user_limit_uses_admin_default(self):
        settings_row = BidSystemSettings.objects.get(pk=1)
        settings_row.default_bid_limit = 3
        settings_row.save(update_fields=["default_bid_limit"])
        BidRetentionPolicy.objects.create(user=self.user, bid_limit=None)
        self.assertEqual(get_effective_bid_limit(self.user), 3)

    def test_dashboard_displays_current_count_and_blocks_creation_at_limit(self):
        Bid.objects.create(uploaded_by=self.user, source_pdf=self.pdf_upload())
        self.client.force_login(self.user)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1 / 1")
        self.assertContains(response, "maximum active bid limit of 1")
        self.assertContains(response, 'data-at-limit="true"')

    def test_requirement_analysis_uses_local_rules(self):
        analysis = analyze_requirements(
            "Years of Past Experience Required: 3 years. "
            "Minimum Average Annual Turnover of the bidder must be submitted. "
            "Please provide GST registration certificate."
        )

        self.assertEqual(analysis.extraction_confidence, "low")
        self.assertEqual(
            {requirement.document_type for requirement in analysis.requirements},
            {"experience_declaration", "bidder_turnover"},
        )
        self.assertEqual(
            [document["document_type"] for document in analysis.required_company_documents],
            ["gst"],
        )
        self.assertIn("matched locally", analysis.notes)
        self.assertTrue(analysis.has_unverified_data)

    def test_admin_can_set_audited_user_override_but_regular_user_cannot(self):
        admin_user = get_user_model().objects.create_superuser(username="site-admin", email="admin@example.test", password="test-password")
        admin_client = APIClient()
        admin_client.force_login(admin_user)
        response = admin_client.post(reverse("admin:bids_bidretentionpolicy_add"), {
            "user": self.user.pk,
            "bid_limit": "4",
            "change_reason": "Customer requested additional capacity",
            "_save": "Save",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(get_effective_bid_limit(self.user), 4)
        audit = BidLimitAudit.objects.get(user=self.user)
        self.assertEqual((audit.old_limit, audit.new_limit), (1, 4))
        self.assertEqual(audit.reason, "Customer requested additional capacity")
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("admin:bids_bidretentionpolicy_changelist")).status_code, 302)

    def test_expired_bid_cleanup_removes_temporary_files_only(self):
        bid = Bid.objects.create(uploaded_by=self.user, source_pdf=self.pdf_upload())
        profile = CompanyProfile.objects.create(owner=self.user, legal_name="Keep Me Ltd")
        reusable = CompanyDocument.objects.create(company=profile, title="GST", document_type="gst")
        reusable.file.save("gst.pdf", ContentFile(b"reusable"), save=True)
        reusable_name = reusable.file.name
        bid.created_at = timezone.now() - timedelta(days=31)
        Bid.objects.filter(pk=bid.pk).update(created_at=bid.created_at)
        settings_row = BidSystemSettings.objects.get(pk=1)
        settings_row.active_bid_expiry_days = 30
        settings_row.save(update_fields=["active_bid_expiry_days"])
        from .retention import expire_old_bids
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(expire_old_bids(), 1)
        self.assertFalse(Bid.objects.filter(pk=bid.pk).exists())
        self.assertTrue(reusable.file.storage.exists(reusable_name))


@skipUnlessDBFeature("supports_transactions")
class BidCreationConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.temp_media = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.temp_media.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(self.temp_media.cleanup)
        self.user = get_user_model().objects.create_user(username="concurrent-owner", password="test-password")

    @patch("apps.bids.tasks.extract_bid_pdf.delay", return_value=SimpleNamespace(id="extract-job"))
    def test_simultaneous_creates_cannot_exceed_limit(self, _delay):
        def create_bid(number):
            close_old_connections()
            client = APIClient()
            client.force_authenticate(self.user)
            upload = SimpleUploadedFile(f"bid-{number}.pdf", b"%PDF-1.4\nminimal", content_type="application/pdf")
            response = client.post("/api/bids/", {"bid_number": f"GEM/2026/B/{number}", "source_pdf": upload}, format="multipart")
            close_old_connections()
            return response.status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(create_bid, (1, 2)))
        self.assertCountEqual(responses, [201, 409])
        self.assertEqual(Bid.objects.filter(uploaded_by=self.user).count(), 1)
