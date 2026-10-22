import io
import math
import tempfile
from datetime import date
from unittest.mock import patch

import pymupdf
from PIL import Image, ImageDraw
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from django.urls import reverse
from openpyxl import Workbook
from reportlab.pdfgen import canvas as pdf_canvas

from apps.bids.models import Bid
from apps.companies.models import CompanyProfile
from apps.documents.models import LinkedDocument
from apps.processing.models import ProcessingJob
from services.documents.downloader import DownloadedFile
from .boq_extraction import extract_boq_tables, extracted_boq_tables, import_boq_tables
from .forms import CustomDocumentForm
from .extraction import suggested_preparation_values
from .models import BidPreparation, BidBOQItem, GeneratedDocument
from .services.pdf_documents import DOCUMENTS, build_document
from apps.bids.tasks import process_linked_document


class EditableGeneratedDocumentTests(TestCase):
    def setUp(self):
        self.temp_media = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.temp_media.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(self.temp_media.cleanup)
        self.user = get_user_model().objects.create_user(username="document-owner", password="test-password")
        self.bid = Bid.objects.create(
            uploaded_by=self.user,
            source_pdf=SimpleUploadedFile("bid.pdf", b"%PDF-1.4\nminimal bid", content_type="application/pdf"),
            bid_number="GEM/2026/B/1234567",
            title="Example OFC work",
        )
        self.prep = BidPreparation.objects.create(
            bid=self.bid,
            bid_number=self.bid.bid_number,
            bid_title=self.bid.title,
            buyer_name="Example Buyer",
            buyer_department="Network Department",
        )
        self.profile = CompanyProfile.objects.create(
            owner=self.user,
            legal_name="Example Networks",
            address="12 Main Road",
            city="Patna",
            state="Bihar",
            signatory_name="Aniket Kumar",
            signature_document_types=["experience_declaration", "boq_specifications"],
        )

    @staticmethod
    def pdf_text(pdf_bytes):
        pdf = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        try:
            return "\n".join(page.get_text() for page in pdf)
        finally:
            pdf.close()

    def test_default_editor_text_contains_all_rendered_header_and_signatory_content(self):
        _title, editable_text, pdf = build_document(self.profile, self.prep, "experience_declaration")
        output = self.pdf_text(pdf)
        for visible in (
            "M/S EXAMPLE NETWORKS",
            "PATNA, BIHAR",
            "EXPERIENCE DECLARATION",
            "GEM/2026/B/1234567",
            "Example Buyer",
            "Experience criteria declaration",
            "Declaration",
            "Authorized Signatory",
            "Company Seal and Stamp",
            "Name: Aniket Kumar",
            "Place: Patna, Bihar",
        ):
            with self.subTest(visible=visible):
                self.assertIn(visible, editable_text)
                self.assertIn(visible, " ".join(output.split()))
        self.assertNotIn("PAN:", editable_text)
        self.assertNotIn("GeM Bid No.:", editable_text)
        self.assertNotIn("Date: 05/10/26", editable_text)
        self.assertIn("Authorized Signatory", editable_text)
        self.assertIn("Company Seal and Stamp", output)
        self.assertIn("GeM Bid No. GEM/2026/B/1234567", " ".join(output.split()))

    def test_company_seal_label_is_centered_to_the_right_of_signatory_name(self):
        _title, _editable_text, pdf = build_document(self.profile, self.prep, "experience_declaration")
        page = pymupdf.open(stream=pdf, filetype="pdf")[0]
        name_rects = page.search_for("Name: Aniket Kumar")
        seal_rects = page.search_for("Company Seal and Stamp")

        self.assertEqual(len(name_rects), 1)
        self.assertEqual(len(seal_rects), 1)
        name_rect = name_rects[0]
        seal_rect = seal_rects[0]
        self.assertGreater((seal_rect.x0 + seal_rect.x1) / 2, page.rect.width / 2)
        self.assertGreater(seal_rect.x0, name_rect.x1)
        self.assertAlmostEqual(
            (seal_rect.y0 + seal_rect.y1) / 2,
            (name_rect.y0 + name_rect.y1) / 2,
            delta=2,
        )

    def test_footer_date_and_place_are_left_aligned_below_signatory_name(self):
        _title, _editable_text, pdf = build_document(self.profile, self.prep, "experience_declaration")
        page = pymupdf.open(stream=pdf, filetype="pdf")[0]
        name_rect = page.search_for("Name: Aniket Kumar")[0]
        date_rect = page.search_for(f"Date: {timezone.localdate().strftime('%d %B %Y')}")[0]
        place_rect = page.search_for("Place: Patna, Bihar")[0]

        self.assertAlmostEqual(name_rect.x0, date_rect.x0, delta=1)
        self.assertAlmostEqual(name_rect.x0, place_rect.x0, delta=1)
        self.assertGreater(date_rect.y0, name_rect.y0)
        self.assertGreater(place_rect.y0, date_rect.y0)

    def test_letterhead_keeps_locality_and_omits_full_street_address_and_pan(self):
        self.profile.address = (
            "WARD-9, CHANDRABHAN TOLA, AUNTA MAIN ROAD, NEAR PRIYANKA STUDIO"
        )
        self.profile.city = "Patna"
        self.profile.state = "Bihar"
        self.profile.pincode = "803303"
        self.profile.gstin = "10HKYPK5816H1ZS"
        self.profile.pan = "HKYPK5816H"
        self.profile.save()
        self.prep.bid_number = "GEM/2026/B/7968723"
        self.prep.bid_date = date(2020, 9, 17)
        self.prep.save()
        self.profile.legal_name = "Aniket Kumar"
        self.profile.save(update_fields=["legal_name"])

        _title, editable_text, pdf = build_document(
            self.profile,
            self.prep,
            "additional_doc_1",
        )
        output = self.pdf_text(pdf)
        for expected in (
            "M/S ANIKET KUMAR",
            "AUNTA, PATNA, BIHAR, 803303",
            "GSTIN: 10HKYPK5816H1ZS",
            "ADDITIONAL DOCUMENT 1 – BOQ COMPLIANCE",
            "Authorized Signatory",
            "Company Seal and Stamp",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, editable_text)
                self.assertIn(expected, output)
        self.assertNotIn("GeM Bid No.:", editable_text)
        self.assertNotIn("Date: 17/09/20", editable_text)
        self.assertIn("GeM Bid No. GEM/2026/B/7968723", " ".join(output.split()))
        for excluded in ("WARD-9", "CHANDRABHAN TOLA", "MAIN ROAD", "PRIYANKA STUDIO", "PAN:"):
            with self.subTest(excluded=excluded):
                self.assertNotIn(excluded, editable_text)
                self.assertNotIn(excluded, output)

    def test_duplicate_bid_metadata_before_letterhead_is_removed(self):
        self.profile.address = "MOKAMEH"
        self.profile.city = "Patna"
        self.profile.state = "Bihar"
        self.profile.pincode = "803303"
        self.profile.save()
        duplicated_header = (
            "GeM Bid No.: GEM/2026/B/7932962\n"
            "Date: 05/10/26\n\n"
            "M/S ANIKET KUMAR\n"
            "MOKAMEH, PATNA, BIHAR, 803303\n"
            "GSTIN: 10HKYPK5816H1ZS\n\n"
            "EXPERIENCE DECLARATION\n\n"
            "GeM Bid No.: GEM/2026/B/7932962\n"
            "Date: 05/10/26\n\n"
            "To: The Head of Department\n\n"
            "Experience criteria declaration for the MOKAMEH office."
        )

        _title, editable_text, pdf = build_document(
            self.profile,
            self.prep,
            "experience_declaration",
            duplicated_header,
        )
        output = self.pdf_text(pdf)

        self.assertNotIn("GeM Bid No.:", editable_text)
        self.assertNotIn("GeM Bid No.:", output)
        self.assertNotIn("Date: 05/10/26", editable_text)
        self.assertNotIn("Date: 05/10/26", output)
        self.assertEqual(output.count("EXPERIENCE DECLARATION"), 1)
        self.assertIn("AUNTA, PATNA, BIHAR, 803303", output)
        self.assertNotIn("MOKAMEH", output)
        self.assertIn("To: The Head of Department", output)
        self.assertIn("Experience criteria declaration for the AUNTA office.", output)
        self.assertIn("GeM Bid No. GEM/2026/B/1234567", " ".join(output.split()))
        self.assertIn("Company Seal and Stamp", output)

    def test_manual_edits_are_rendered_without_hidden_default_text(self):
        edited = "Edited title\n\nBid: GEM/2026/B/1234567\n\nCustom clause: manually updated\n\nSignature:\n\nPlace: Patna, Bihar"
        _title, returned_text, pdf = build_document(self.profile, self.prep, "experience_declaration", edited)
        output = self.pdf_text(pdf)
        self.assertIn("Custom clause: manually updated", output)
        self.assertNotIn("Example Networks", output)
        self.assertIn("Authorized Signatory", output)
        self.assertIn("Company Seal and Stamp", output)

    def test_msme_turnover_exemption_template_is_registered_and_uses_profile_details(self):
        self.profile.enterprise_type = CompanyProfile.EnterpriseType.MICRO
        self.profile.udyam_number = "UDYAM-BR-01-0001234"
        self.profile.save(update_fields=["enterprise_type", "udyam_number"])

        title, editable_text, pdf = build_document(
            self.profile,
            self.prep,
            "msme_turnover_exemption",
        )
        output = self.pdf_text(pdf)

        self.assertEqual(title, "MSME Turnover Exemption Declaration")
        self.assertIn("MSME Turnover Exemption Declaration", editable_text)
        self.assertIn("UDYAM-BR-01-0001234", editable_text)
        self.assertIn("minimum average annual turnover requirement", output)
        self.assertIn("UDYAM-BR-01-0001234", output)
        self.assertIn("Signature:", output)

    def test_first_page_department_then_organization_are_rendered_dynamically(self):
        first_page_text = (
            "Buyer Organisation Name: Defence Laboratory\n"
            "Buyer Department Name: Department of Defence Research & Development\n\n"
            "To: Office Of Dg ( Ns & M)\n"
            "Department Of Defence Research & Development\n"
            "Ministry of Defence\n\n"
            "Bid End Date: 30/12/2026"
        )
        self.bid.extracted_text = (
            first_page_text
            + "\n\nBuyer Organisation Name: Wrong value from a later page"
        )
        self.bid.extracted_metadata = {"first_page_text": first_page_text}
        self.bid.save(update_fields=["extracted_text", "extracted_metadata"])

        suggested = suggested_preparation_values(self.bid)
        self.prep.beneficiary_details = suggested["beneficiary_details"]
        self.prep.buyer_department = suggested["buyer_department"]
        self.prep.buyer_name = suggested["buyer_name"]
        self.prep.save(update_fields=["beneficiary_details", "buyer_department", "buyer_name"])
        _title, editable_text, pdf = build_document(
            self.profile,
            self.prep,
            "experience_declaration",
        )
        output = self.pdf_text(pdf)

        self.assertEqual(
            self.prep.beneficiary_details,
            "Office Of Dg ( Ns & M)\nDepartment Of Defence Research & Development\nMinistry of Defence",
        )
        self.assertIn("To: Department of Defence Research & Development", editable_text)
        self.assertIn("Defence Laboratory", editable_text)
        self.assertIn("Department of Defence Research & Development", output)
        self.assertIn("Defence Laboratory", output)
        self.assertLess(
            editable_text.index("Department of Defence Research & Development"),
            editable_text.index("Defence Laboratory"),
        )
        self.assertNotIn("Ministry of Defence", editable_text)
        self.assertNotIn("Office Of Dg", editable_text)
        self.assertNotIn("Wrong value from a later page", editable_text)
        for document_type, _label in DOCUMENTS:
            with self.subTest(document_type=document_type):
                _title, content, generated_pdf = build_document(
                    self.profile,
                    self.prep,
                    document_type,
                )
                self.assertIn("To: Department of Defence Research & Development", content)
                self.assertIn("Defence Laboratory", content)
                self.assertIn("Department of Defence Research & Development", self.pdf_text(generated_pdf))
                self.assertIn("Defence Laboratory", self.pdf_text(generated_pdf))

    def test_source_pdf_filename_lines_are_removed_from_every_generated_template(self):
        source_line = "Source: Past_Performance_GEM_2026_B_7968723_UPDATED.pdf"
        content = f"Generated document\n\n{source_line}\n\nSource: GeM bid portal"

        for document_type, _label in DOCUMENTS:
            with self.subTest(document_type=document_type):
                _title, returned_text, pdf = build_document(
                    self.profile,
                    self.prep,
                    document_type,
                    content,
                )
                self.assertNotIn(source_line, returned_text)
                self.assertNotIn(source_line, self.pdf_text(pdf))
                self.assertIn("Source: GeM bid portal", returned_text)
                self.assertIn("Source: GeM bid portal", self.pdf_text(pdf))
                self.assertIn("Company Seal and Stamp", returned_text)
                self.assertIn("Name: Aniket Kumar", self.pdf_text(pdf))

        _title, returned_text, pdf = build_document(
            self.profile,
            self.prep,
            "custom_test",
            content,
            "Custom PDF",
        )
        self.assertNotIn(source_line, returned_text)
        self.assertNotIn(source_line, self.pdf_text(pdf))

    def test_editable_boq_rows_match_rows_rendered_in_pdf(self):
        BidBOQItem.objects.create(preparation=self.prep, description="OFC cable", quantity=25, unit="Meter")
        _title, editable_text, pdf = build_document(self.profile, self.prep, "additional_doc_1")
        output = self.pdf_text(pdf)
        for value in ("BoQ item responses", "Item / requirement", "OFC cable", "25", "Meter", "Complied"):
            with self.subTest(value=value):
                self.assertIn(value, editable_text)
                self.assertIn(value, output)
        boq_header = next(line for line in editable_text.splitlines() if line.startswith("Item / requirement"))
        self.assertEqual(boq_header.split(" | ")[-1], "Bidder response / evidence")
        boq_row = next(line for line in editable_text.splitlines() if line.startswith("OFC cable"))
        self.assertEqual(boq_row.split(" | ")[-1], "Complied")

    def test_manual_boq_form_defaults_bidder_response_to_complied(self):
        self.client.force_login(self.user)
        BidBOQItem.objects.create(
            preparation=self.prep,
            description="OFC cable",
            bidder_response="",
        )
        response = self.client.get(reverse("bid-prepare", args=[self.bid.pk]))
        self.assertContains(response, 'value="Complied"')

    def test_boq_tables_are_extracted_from_bid_pdf_and_linked_csv_and_rendered(self):
        source_pdf = io.BytesIO()
        pdf_canvas_doc = pdf_canvas.Canvas(source_pdf)
        for row_index, row in enumerate((
            ("Item No.", "Item Description", "Quantity", "Unit", "Specification"),
            ("1", "Fiber cable", "120", "Meter", "Single mode, 24 core"),
            ("2", "Splice closure", "4", "Each", "Outdoor, 24 core"),
        )):
            x = 40
            for cell in row:
                pdf_canvas_doc.drawString(x, 760 - row_index * 24, cell)
                x += 105
        pdf_canvas_doc.save()
        pdf_tables = extract_boq_tables(source_pdf.getvalue(), "bid.pdf", "application/pdf")
        self.assertEqual(len(pdf_tables), 1)
        self.assertEqual(pdf_tables[0]["items"][0]["description"], "Fiber cable")

        linked_csv = (
            "Sl. No.,Item Description,Quantity,UOM,Technical Specifications,Make,Model\n"
            "1,UPS battery,8,Nos,12V 150Ah,ExampleCo,B-150\n"
            "1,UPS battery,8,Nos,12V 150Ah,ExampleCo,B-150\n"
            "2,Network switch,2,Nos,24 port managed,ExampleCo,SW-24\n"
        ).encode()
        csv_tables = extract_boq_tables(linked_csv, "BOQ.csv", "text/csv")
        self.assertEqual(csv_tables[0]["items"][0]["description"], "UPS battery")
        self.assertEqual(csv_tables[0]["items"][0]["source_data"]["Model"], "B-150")

        self.assertEqual(import_boq_tables(self.prep, pdf_tables + csv_tables), 5)
        self.assertEqual(import_boq_tables(self.prep, pdf_tables + csv_tables), 0)
        displayed = extracted_boq_tables(self.prep)
        self.assertEqual(len(displayed), 2)
        self.assertIn("Technical Specifications", displayed[1]["headers"])
        self.assertEqual(displayed[1]["headers"][-1], "Bidder Response")
        self.assertEqual(displayed[1]["rows"][0]["cells"][-1], "Complied")
        self.assertEqual(self.prep.boq_items.count(), 5)

        _title, editable_content, pdf_bytes = build_document(
            self.profile,
            self.prep,
            "boq_specifications",
        )
        pdf_output = self.pdf_text(pdf_bytes)
        normalized_pdf_output = " ".join(pdf_output.split())
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as generated_pdf:
            page = generated_pdf[0]
            response_header_rects = page.search_for("Bidder Response")
            self.assertTrue(response_header_rects)
            self.assertGreater(max(rect.x0 for rect in response_header_rects), page.rect.width * 0.7)
        expected_values = (
            "Bill of quantities",
            "Source BoQ table: bid.pdf · table 1",
            "Item No.",
            "Item Description",
            "Quantity",
            "Unit",
            "Specification",
            "Bidder Response",
            "Fiber cable",
            "Single mode, 24 core",
            "Source BoQ table: BOQ.csv",
            "Sl. No.",
            "UOM",
            "Technical Specifications",
            "Make",
            "Model",
            "UPS battery",
            "12V 150Ah",
            "ExampleCo",
            "B-150",
            "Complied",
        )
        for value in expected_values:
            with self.subTest(value=value):
                self.assertIn(value, editable_content)
                self.assertIn(value, normalized_pdf_output)
        self.assertIn("| Complied", editable_content)
        for line in editable_content.splitlines():
            if line.startswith(("1 | Fiber cable", "1 | UPS battery")):
                self.assertEqual(line.split(" | ")[-1], "Complied")

        self.client.force_login(self.user)
        response = self.client.get(reverse("bid-prepare", args=[self.bid.pk]))
        self.assertContains(response, "Technical Specifications")
        self.assertContains(response, "Single mode, 24 core")
        self.assertContains(response, "B-150")

    def test_boq_tables_are_extracted_from_xlsx(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Pricing"
        sheet.append(["Item Description", "Quantity", "Unit", "Specification"])
        sheet.append(["Copper cable", 24, "Meter", "CAT6"])
        spreadsheet = io.BytesIO()
        workbook.save(spreadsheet)

        tables = extract_boq_tables(
            spreadsheet.getvalue(),
            "BOQ.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0]["items"][0]["description"], "Copper cable")
        self.assertEqual(tables[0]["items"][0]["quantity"], "24")
        self.assertEqual(tables[0]["items"][0]["source_data"]["Specification"], "CAT6")

        content_sniffed_tables = extract_boq_tables(
            spreadsheet.getvalue(),
            "download.pdf",
            "application/octet-stream",
        )
        self.assertEqual(content_sniffed_tables[0]["items"][0]["description"], "Copper cable")

    @patch("apps.bids.tasks.download_document")
    def test_linked_document_task_imports_downloaded_csv_boq(self, download):
        csv_content = (
            "Item Description,Quantity,UOM,Technical Specifications\n"
            "Network switch,2,Nos,24 port managed\n"
        ).encode()
        download.return_value = DownloadedFile(
            content=csv_content,
            filename="BOQ.csv",
            content_type="text/csv",
            final_url="https://example.test/BOQ.csv",
        )
        linked_document = LinkedDocument.objects.create(
            bid=self.bid,
            url="https://example.test/BOQ.csv",
            label="Bill of Quantities",
            depth=1,
        )
        job = ProcessingJob.objects.create(bid=self.bid)

        result = process_linked_document.apply(
            args=(linked_document.pk, job.pk),
            throw=True,
        ).result

        self.assertEqual(result, LinkedDocument.Status.DOWNLOADED)
        self.assertEqual(self.prep.boq_items.count(), 1)
        self.assertEqual(self.prep.boq_items.get().description, "Network switch")
        self.assertEqual(job.__class__.objects.get(pk=job.pk).status, ProcessingJob.Status.SUCCEEDED)
        self.prep.boq_items.all().delete()
        self.client.force_login(self.user)
        preparation_page = self.client.get(reverse("bid-prepare", args=[self.bid.pk]))
        self.assertEqual(preparation_page.status_code, 200)
        self.assertNotContains(
            preparation_page,
            "No machine-readable BoQ table with recognizable item and quantity columns",
        )
        self.assertContains(preparation_page, "BOQ.csv")
        self.assertContains(preparation_page, "Network switch")
        self.assertEqual(self.prep.boq_items.count(), 1)
        _title, editable_content, pdf_bytes = build_document(
            self.profile,
            self.prep,
            "boq_specifications",
        )
        pdf_output = self.pdf_text(pdf_bytes)
        normalized_pdf_output = " ".join(pdf_output.split())
        for content in (
            "COMPLIANCE TO BOQ SPECIFICATIONS",
            "Example Buyer",
            "1. Compliance with BoQ Specifications",
            "Network switch",
            "24 port managed",
            "Complied",
            "Bidder responses default to Complied.",
        ):
            with self.subTest(content=content):
                self.assertIn(content, editable_content)
                self.assertIn(content, normalized_pdf_output)
        self.assertNotIn("Extracted BoQ details and bidder response", editable_content)
        self.assertNotIn("Extracted BoQ details and bidder response", normalized_pdf_output)

        saved_document = GeneratedDocument.objects.create(
            bid=self.bid,
            document_type="boq_specifications",
            title="Compliance to BoQ Specifications",
            editable_content=(
                "Legacy BoQ compliance text\n\n"
                "Bill of quantities\n\n"
                "Source BoQ table: BOQ.csv\n"
                "Item Description | Quantity | UOM\n"
                "Network switch | 2 | Nos\n\n"
                "Extracted BoQ details and bidder response\n"
                "Item / requirement | Quantity | Unit | Bidder response / evidence\n"
                "Network switch | 2 | Nos | Needs Review"
            ),
            template_version="2.3",
            generated_by=self.user,
        )
        self.client.force_login(self.user)
        saved_response = self.client.get(
            reverse("generated-document-view", args=[saved_document.pk])
        )
        self.assertEqual(saved_response.status_code, 200)
        saved_document.refresh_from_db()
        self.assertEqual(saved_document.template_version, "2.5")
        self.assertNotIn("Extracted BoQ details and bidder response", saved_document.editable_content)
        self.assertEqual(saved_document.editable_content.count("Source BoQ table:"), 1)
        self.assertIn("Bill of quantities", saved_document.editable_content)
        self.assertIn("Technical Specifications", saved_document.editable_content)
        source_header = next(
            line
            for line in saved_document.editable_content.splitlines()
            if line.endswith("| Bidder Response")
        )
        source_row = next(
            line
            for line in saved_document.editable_content.splitlines()
            if "Network switch" in line and line.endswith("| Complied")
        )
        self.assertEqual(source_header.split(" | ")[-1], "Bidder Response")
        self.assertEqual(source_row.split(" | ")[-1], "Complied")
        self.assertIn("Bill of quantities", self.pdf_text(saved_response.content))
        self.assertIn("Bidder Response", self.pdf_text(saved_response.content))
        self.assertIn("Complied", self.pdf_text(saved_response.content))
        self.assertNotIn("Extracted BoQ details and bidder response", self.pdf_text(saved_response.content))

    def test_stamp_rotation_and_size_are_applied_to_generated_pdf(self):
        image_data = io.BytesIO()
        Image.new("RGBA", (180, 100), "blue").save(image_data, format="PNG")
        self.profile.stamp_image.save(
            "seal.png",
            ContentFile(image_data.getvalue()),
            save=False,
        )
        self.profile.stamp_rotation = 90
        self.profile.stamp_scale = "1.25"
        self.profile.save()

        _title, _content, pdf_bytes = build_document(
            self.profile,
            self.prep,
            "experience_declaration",
            "Signature:",
        )

        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as pdf:
            images = pdf[0].get_images(full=True)
            self.assertTrue(images)
            xref = images[0][0]
            image_info = pdf.extract_image(xref)
            stamp_rect = pdf[0].get_image_rects(xref)[0]
        self.assertEqual((image_info["width"], image_info["height"]), (100, 180))

        self.profile.stamp_scale = "1.0"
        self.profile.save(update_fields=["stamp_scale"])
        _title, _content, base_pdf_bytes = build_document(
            self.profile,
            self.prep,
            "experience_declaration",
            "Signature:",
        )
        with pymupdf.open(stream=base_pdf_bytes, filetype="pdf") as pdf:
            base_xref = pdf[0].get_images(full=True)[0][0]
            base_stamp_rect = pdf[0].get_image_rects(base_xref)[0]
        self.assertAlmostEqual(stamp_rect.width / base_stamp_rect.width, 1.25, places=2)
        self.assertAlmostEqual(stamp_rect.height / base_stamp_rect.height, 1.25, places=2)

    def test_generated_pdf_embeds_stamp_with_transparent_background(self):
        image = Image.new("RGB", (180, 100), "white")
        ImageDraw.Draw(image).ellipse((35, 15, 145, 85), outline=(190, 25, 35), width=8)
        image_data = io.BytesIO()
        image.save(image_data, format="PNG")
        self.profile.stamp_image.save("white-background-stamp.png", ContentFile(image_data.getvalue()), save=True)

        _title, _content, pdf_bytes = build_document(
            self.profile,
            self.prep,
            "experience_declaration",
            "Signature:",
        )

        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as pdf:
            images = pdf[0].get_images(full=True)
            self.assertEqual(len(images), 1)
            self.assertGreater(images[0][1], 0, "The stamp should be embedded with a soft transparency mask.")

    def test_company_profile_stamp_settings_are_saved_and_used_in_generated_pdf(self):
        image_data = io.BytesIO()
        Image.new("RGBA", (180, 100), "blue").save(image_data, format="PNG")
        self.profile.stamp_image.save("seal.png", ContentFile(image_data.getvalue()), save=True)
        document = GeneratedDocument.objects.create(
            bid=self.bid,
            document_type="experience_declaration",
            title="Experience Declaration",
            editable_content="Experience Declaration\n\nSignature:\n\nPlace: Patna, Bihar",
            generated_by=self.user,
        )
        self.client.force_login(self.user)

        response = self.client.post("/companies/profile/", {
            "form_action": "signature",
            "signature_style": "blue_ink",
            "signature_rotation": "0",
            "signature_scale": "1",
            "stamp_rotation": "90",
            "stamp_scale": "1.5",
            "signature_document_types": ["experience_declaration"],
            "stamp_document_types": ["experience_declaration"],
        })

        self.assertRedirects(response, "/companies/profile/")
        self.profile.refresh_from_db()
        self.assertEqual(str(self.profile.stamp_rotation), "90.0")
        self.assertEqual(str(self.profile.stamp_scale), "1.50")

        pdf_response = self.client.get(reverse("generated-document-view", args=[document.pk]))
        self.assertEqual(pdf_response.status_code, 200)
        with pymupdf.open(stream=pdf_response.content, filetype="pdf") as pdf:
            stamp_xref = pdf[0].get_images(full=True)[0][0]
            image_info = pdf.extract_image(stamp_xref)
            stamp_rect = pdf[0].get_image_rects(stamp_xref)[0]
        self.assertEqual((image_info["width"], image_info["height"]), (100, 180))
        self.assertGreater(stamp_rect.height, 29 * 72 / 25.4)

    def test_editor_preview_uses_signature_angle_saved_in_company_profile(self):
        image = Image.new("RGB", (240, 80), "white")
        draw = ImageDraw.Draw(image)
        draw.line((25, 40, 210, 40), fill=(15, 35, 190), width=7)
        image_data = io.BytesIO()
        image.save(image_data, format="PNG")
        self.profile.signature_image.save(
            "signature.png",
            ContentFile(image_data.getvalue()),
            save=True,
        )
        self.profile.signature_document_types = ["experience_declaration"]
        self.profile.save(update_fields=["signature_document_types"])
        document = GeneratedDocument.objects.create(
            bid=self.bid,
            document_type="experience_declaration",
            title="Experience Declaration",
            editable_content="Experience Declaration\n\nSignature:\n\nPlace: Patna, Bihar",
            generated_by=self.user,
        )
        self.client.force_login(self.user)

        profile_response = self.client.post("/companies/profile/", {
            "form_action": "signature",
            "signature_style": "blue_ink",
            "signature_rotation": "30",
            "signature_scale": "1",
            "stamp_rotation": "0",
            "stamp_scale": "1",
            "signature_document_types": ["experience_declaration"],
        })
        self.assertRedirects(profile_response, "/companies/profile/")
        self.profile.refresh_from_db()
        self.assertEqual(str(self.profile.signature_rotation), "30.0")

        editor_response = self.client.get(reverse("generated-document-edit", args=[document.pk]))
        self.assertContains(
            editor_response,
            f'{reverse("generated-document-view", args=[document.pk])}?v={int(self.profile.updated_at.timestamp() * 1_000_000)}',
        )
        self.assertNotContains(editor_response, "Placed in the PDF at the signature line")
        self.assertNotContains(editor_response, "placed-marks-preview")

        pdf_response = self.client.post(
            reverse("generated-document-preview", args=[document.pk]),
            {"editable_content": document.editable_content},
        )
        with pymupdf.open(stream=pdf_response.content, filetype="pdf") as pdf:
            signature_xref = pdf[0].get_images(full=True)[0][0]
            signature_image = pdf.extract_image(signature_xref)
            signature_rect = pdf[0].get_image_rects(signature_xref)[0]
            page_width = pdf[0].rect.width
        actual_center_x = (signature_rect.x0 + signature_rect.x1) / 2
        expected_center_x = 20 * 72 / 25.4 + 6 + signature_rect.width / 2
        self.assertAlmostEqual(actual_center_x, expected_center_x, delta=2)

        with Image.open(io.BytesIO(signature_image["image"])) as rendered_signature:
            rendered_signature = rendered_signature.convert("RGBA")
            signature_pixels = [
                (x, y)
                for y in range(rendered_signature.height)
                for x in range(rendered_signature.width)
                if (pixel := rendered_signature.getpixel((x, y)))[3] > 0
                and pixel[2] > pixel[0] * 2
            ]
        mean_x = sum(x for x, _ in signature_pixels) / len(signature_pixels)
        mean_y = sum(y for _, y in signature_pixels) / len(signature_pixels)
        covariance_xx = sum((x - mean_x) ** 2 for x, _ in signature_pixels)
        covariance_yy = sum((y - mean_y) ** 2 for _, y in signature_pixels)
        covariance_xy = sum((x - mean_x) * (y - mean_y) for x, y in signature_pixels)
        rendered_angle = 0.5 * math.degrees(math.atan2(2 * covariance_xy, covariance_xx - covariance_yy))
        self.assertAlmostEqual(rendered_angle, 30, delta=5)
        with pymupdf.open(stream=pdf_response.content, filetype="pdf") as pdf:
            rendered_page = pdf[0].get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
        page_pixels = rendered_page.samples
        page_width = rendered_page.width
        blue_points = []
        for offset in range(0, len(page_pixels), rendered_page.n):
            red, green, blue = page_pixels[offset:offset + 3]
            if blue > red * 2 and blue > green * 2:
                pixel_index = offset // rendered_page.n
                blue_points.append((pixel_index % page_width, pixel_index // page_width))
        mean_x = sum(x for x, _ in blue_points) / len(blue_points)
        mean_y = sum(y for _, y in blue_points) / len(blue_points)
        covariance_xx = sum((x - mean_x) ** 2 for x, _ in blue_points)
        covariance_yy = sum((y - mean_y) ** 2 for _, y in blue_points)
        covariance_xy = sum((x - mean_x) * (y - mean_y) for x, y in blue_points)
        rendered_pdf_angle = 0.5 * math.degrees(math.atan2(2 * covariance_xy, covariance_xx - covariance_yy))
        self.assertAlmostEqual(rendered_pdf_angle, 30, delta=5)
        self.profile.signature_position_x = "55.00"
        self.profile.signature_position_y = "35.00"
        self.profile.save()
        updated_preview = self.client.post(
            reverse("generated-document-preview", args=[document.pk]),
            {"editable_content": document.editable_content},
        )
        updated_editor = self.client.get(reverse("generated-document-edit", args=[document.pk]))
        self.assertNotContains(updated_editor, "Placed in the PDF at the signature line")

    def test_saved_signature_and_stamp_positions_move_in_generated_pdf(self):
        signature_image = Image.new("RGB", (240, 80), "white")
        ImageDraw.Draw(signature_image).line((20, 40, 220, 40), fill=(15, 35, 190), width=8)
        signature_data = io.BytesIO()
        signature_image.save(signature_data, format="PNG")
        self.profile.signature_image.save(
            "position-signature.png",
            ContentFile(signature_data.getvalue()),
            save=False,
        )
        stamp_data = io.BytesIO()
        Image.new("RGBA", (180, 100), (200, 20, 20, 255)).save(stamp_data, format="PNG")
        self.profile.stamp_image.save(
            "position-stamp.png",
            ContentFile(stamp_data.getvalue()),
            save=False,
        )
        self.profile.signature_document_types = ["experience_declaration"]
        self.profile.save()

        def image_centers(pdf_bytes):
            centers = {}
            with pymupdf.open(stream=pdf_bytes, filetype="pdf") as pdf:
                for xref, *_rest in pdf[0].get_images(full=True):
                    image_info = pdf.extract_image(xref)
                    with Image.open(io.BytesIO(image_info["image"])) as image:
                        pixels = list(image.convert("RGBA").getdata())
                    red_pixels = sum(red > blue + 40 and red > green + 40 for red, green, blue, alpha in pixels if alpha)
                    blue_pixels = sum(blue > red + 40 and blue > green + 40 for red, green, blue, alpha in pixels if alpha)
                    key = "stamp" if red_pixels > blue_pixels else "signature"
                    rect = pdf[0].get_image_rects(xref)[0]
                    centers[key] = {
                        "center": ((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2),
                        "width": rect.width,
                        "height": rect.height,
                    }
            return centers

        mark_content = "Signature:"
        _title, _content, initial_pdf = build_document(
            self.profile,
            self.prep,
            "experience_declaration",
            mark_content,
        )
        initial = image_centers(initial_pdf)
        old_x = {"signature": float(self.profile.signature_position_x), "stamp": float(self.profile.stamp_position_x)}
        old_y = {"signature": float(self.profile.signature_position_y), "stamp": float(self.profile.stamp_position_y)}
        with pymupdf.open(stream=initial_pdf, filetype="pdf") as pdf:
            page_center_x = pdf[0].rect.width / 2
        self.assertLess(initial["signature"]["center"][0], initial["stamp"]["center"][0])
        self.assertGreater(initial["stamp"]["center"][0], page_center_x)

        self.profile.signature_position_x = "54.25"
        self.profile.signature_position_y = "38.50"
        self.profile.stamp_position_x = "31.75"
        self.profile.stamp_position_y = "62.25"
        self.profile.save(update_fields=[
            "signature_position_x",
            "signature_position_y",
            "stamp_position_x",
            "stamp_position_y",
        ])
        _title, _content, moved_pdf = build_document(
            self.profile,
            self.prep,
            "experience_declaration",
            mark_content,
        )
        moved = image_centers(moved_pdf)

        points_per_mm = 72 / 25.4
        area_width = 170 * points_per_mm - 12
        area_height = 30 * points_per_mm * max(float(self.profile.signature_scale), float(self.profile.stamp_scale), 1)

        def delta(area, size, before, after):
            low, high = size / 2, area - size / 2
            old_center = min(max(before / 100 * area, low), high)
            new_center = min(max(after / 100 * area, low), high)
            return new_center - old_center

        for mark, new_x, new_y in (
            ("signature", 54.25, 38.50),
            ("stamp", 31.75, 62.25),
        ):
            self.assertAlmostEqual(moved[mark]["center"][0] - initial[mark]["center"][0], delta(area_width, initial[mark]["width"], old_x[mark], new_x), delta=1)
            self.assertAlmostEqual(moved[mark]["center"][1] - initial[mark]["center"][1], delta(area_height, initial[mark]["height"], old_y[mark], new_y), delta=1)

    def test_live_editor_positions_are_saved_per_document_and_used_in_pdf(self):
        signature_data = io.BytesIO()
        Image.new("RGB", (100, 40), "blue").save(signature_data, format="PNG")
        self.profile.signature_image.save("editor-signature.png", ContentFile(signature_data.getvalue()), save=True)
        stamp_data = io.BytesIO()
        Image.new("RGB", (60, 60), "red").save(stamp_data, format="PNG")
        self.profile.stamp_image.save("editor-stamp.png", ContentFile(stamp_data.getvalue()), save=True)
        self.profile.signature_document_types = ["experience_declaration"]
        self.profile.save(update_fields=["signature_document_types"])
        self.client.force_login(self.user)
        document = GeneratedDocument.objects.create(
            bid=self.bid,
            document_type="experience_declaration",
            title="Experience Declaration",
            editable_content="Experience Declaration\n\nSignature:",
            generated_by=self.user,
        )
        editor = self.client.get(reverse("generated-document-edit", args=[document.pk]))
        self.assertContains(editor, 'id="document-mark-canvas"')
        self.assertContains(editor, 'data-signature-x="0.00"')
        self.assertContains(editor, 'data-signature-y="50.00"')
        self.assertContains(editor, 'data-stamp-x="77.00"')
        self.assertContains(editor, 'data-stamp-y="50.00"')
        self.assertContains(editor, 'name="signature_position_x" type="range" min="0" max="100" step="1" value="0.00"')
        self.assertContains(editor, 'name="stamp_position_x" type="range" min="0" max="100" step="1" value="77.00"')
        self.assertContains(editor, 'name="stamp_position_x"')

        def image_centers(pdf_bytes):
            centers = {}
            with pymupdf.open(stream=pdf_bytes, filetype="pdf") as pdf:
                for xref, *_rest in pdf[0].get_images(full=True):
                    image_info = pdf.extract_image(xref)
                    with Image.open(io.BytesIO(image_info["image"])) as image:
                        pixels = list(image.convert("RGBA").getdata())
                    red_pixels = sum(
                        red > blue + 40 and red > green + 40
                        for red, green, blue, alpha in pixels if alpha
                    )
                    blue_pixels = sum(
                        blue > red + 40 and blue > green + 40
                        for red, green, blue, alpha in pixels if alpha
                    )
                    name = "stamp" if red_pixels > blue_pixels else "signature"
                    rect = pdf[0].get_image_rects(xref)[0]
                    centers[name] = ((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
            return centers

        def assert_centers_match(actual_pdf, expected_pdf):
            actual = image_centers(actual_pdf)
            expected = image_centers(expected_pdf)
            self.assertEqual(set(actual), {"signature", "stamp"})
            for name in expected:
                self.assertAlmostEqual(actual[name][0], expected[name][0], delta=0.1)
                self.assertAlmostEqual(actual[name][1], expected[name][1], delta=0.1)

        content = "Experience Declaration\n\nSignature:"
        placement = {
            "editable_content": content,
            "signature_position_x": "20",
            "signature_position_y": "45",
            "stamp_position_x": "58",
            "stamp_position_y": "55",
        }
        preview_response = self.client.post(
            reverse("generated-document-preview", args=[document.pk]),
            placement,
        )
        self.assertEqual(preview_response.status_code, 200)
        with pymupdf.open(stream=preview_response.content, filetype="pdf") as pdf:
            self.assertEqual(len(pdf[0].get_images(full=True)), 2)
        preview_pdf = preview_response.content

        response = self.client.post(reverse("generated-document-edit", args=[document.pk]), {
            **placement,
        })
        self.assertRedirects(response, reverse("generated-document-edit", args=[document.pk]))
        document.refresh_from_db()
        self.assertEqual(str(document.signature_position_x), "20.00")
        self.assertEqual(str(document.stamp_position_x), "58.00")

        pdf_response = self.client.get(reverse("generated-document-view", args=[document.pk]))
        assert_centers_match(pdf_response.content, preview_pdf)
        self.assertContains(editor, 'name="open_after_save"')

        download_placement = {
            **placement,
            "signature_position_x": "36",
            "signature_position_y": "26",
            "stamp_position_x": "72",
            "stamp_position_y": "68",
        }
        download_preview = self.client.post(
            reverse("generated-document-preview", args=[document.pk]),
            download_placement,
        )
        download_pdf = download_preview.content
        download_response = self.client.post(
            reverse("generated-document-edit", args=[document.pk]),
            {**download_placement, "download_after_save": "1"},
        )
        self.assertRedirects(
            download_response,
            f"{reverse('generated-document-view', args=[document.pk])}?download=1",
            fetch_redirect_response=False,
        )
        downloaded = self.client.get(reverse("generated-document-view", args=[document.pk]), {"download": "1"})
        assert_centers_match(downloaded.content, download_pdf)

        open_placement = {
            **placement,
            "signature_position_x": "0",
            "signature_position_y": "82",
            "stamp_position_x": "91",
            "stamp_position_y": "19",
        }
        open_preview = self.client.post(
            reverse("generated-document-preview", args=[document.pk]),
            open_placement,
        )
        open_response = self.client.post(
            reverse("generated-document-edit", args=[document.pk]),
            {**open_placement, "open_after_save": "1"},
        )
        self.assertRedirects(
            open_response,
            reverse("generated-document-view", args=[document.pk]),
            fetch_redirect_response=False,
        )
        opened = self.client.get(reverse("generated-document-view", args=[document.pk]))
        assert_centers_match(opened.content, open_preview.content)
        document.refresh_from_db()
        self.assertEqual(str(document.signature_position_x), "0.00")

    def test_prepare_refreshes_legacy_analysis_and_fills_this_bids_details(self):
        self.bid.status = Bid.Status.READY
        self.bid.extracted_text = (
            "GEM/2026/B/9988776\n"
            "BOQ Title: Fibre Optic Cable Supply\n"
            "Organisation Name: National Sample Department\n"
            "Department Name: Telecom Division\n"
            "Buyer Address: 10 Main Road, Patna\n"
            "Years of Past Experience Required\n"
            "3 Years\n"
        )
        self.bid.extracted_metadata = {
            "requirements_analysis": {
                "required_documents": [],
                "notes": "AI analysis failed; no data extracted.",
            }
        }
        self.bid.bid_number = ""
        self.bid.title = ""
        self.bid.save()
        self.prep.bid_number = ""
        self.prep.bid_title = ""
        self.prep.buyer_name = ""
        self.prep.buyer_department = ""
        self.prep.buyer_address = ""
        self.prep.save()

        self.client.force_login(self.user)
        response = self.client.get(reverse("bid-prepare", args=[self.bid.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "AI analysis failed")
        self.assertContains(response, "Experience Declaration")
        self.prep.refresh_from_db()
        self.assertEqual(self.prep.bid_number, "GEM/2026/B/9988776")
        self.assertEqual(self.prep.bid_title, "Fibre Optic Cable Supply")
        self.assertEqual(self.prep.buyer_name, "National Sample Department")
        self.assertEqual(self.prep.buyer_department, "Telecom Division")
        self.assertEqual(self.prep.buyer_address, "10 Main Road, Patna")
        self.bid.refresh_from_db()
        self.assertEqual(
            self.bid.extracted_metadata["requirements_analysis"]["required_documents"][0]["document_type"],
            "experience_declaration",
        )

    def test_prepare_shows_all_pdf_templates_even_when_bid_detects_only_one_requirement(self):
        self.bid.status = Bid.Status.READY
        self.bid.extracted_text = "Years of Past Experience Required"
        self.bid.save(update_fields=["status", "extracted_text"])
        self.client.force_login(self.user)

        response = self.client.get(reverse("bid-prepare", args=[self.bid.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Generate PDFs")
        for _document_type, label in DOCUMENTS:
            with self.subTest(document=label):
                self.assertContains(response, label)

    def test_prepare_redirects_when_bid_is_missing(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("bid-prepare", args=[self.bid.pk + 100]),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertRedirects(response, reverse("bid-dashboard"))
        self.assertContains(response, "That bid is no longer available.")

    def test_prepare_does_not_disclose_another_users_bid(self):
        other_user = get_user_model().objects.create_user(username="private-preparation-owner")
        other_bid = Bid.objects.create(
            uploaded_by=other_user,
            source_pdf=SimpleUploadedFile(
                "private-bid.pdf",
                b"%PDF-1.4\nprivate bid",
                content_type="application/pdf",
            ),
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("bid-prepare", args=[other_bid.pk]), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertRedirects(response, reverse("bid-dashboard"))
        self.assertContains(response, "That bid is no longer available.")

    def test_custom_document_can_be_created_previewed_and_downloaded_for_this_bid(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("bid-prepare", args=[self.bid.pk]), {
            "action": "create_custom",
            "title": "Special Eligibility Certificate",
            "content": "Subject: Special eligibility\n\nWe submit the supporting details requested in this bid.",
            "boq-TOTAL_FORMS": "0",
            "boq-INITIAL_FORMS": "0",
            "boq-MIN_NUM_FORMS": "0",
            "boq-MAX_NUM_FORMS": "1000",
        })

        document = GeneratedDocument.objects.get(bid=self.bid)
        self.assertTrue(document.document_type.startswith("custom_"))
        self.assertRedirects(
            response,
            reverse("generated-document-edit", args=[document.pk]),
        )
        self.assertIn("GEM/2026/B/1234567", document.editable_content)
        self.assertIn("Special eligibility", document.editable_content)
        self.assertIn("Authorized Signatory", document.editable_content)
        self.assertIn("Company Seal and Stamp", document.editable_content)

        preview = self.client.get(reverse("generated-document-view", args=[document.pk]))
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview["Content-Type"], "application/pdf")
        self.assertEqual(preview["X-Frame-Options"], "SAMEORIGIN")
        pdf_text = self.pdf_text(preview.content)
        self.assertIn("SPECIAL ELIGIBILITY CERTIFICATE", pdf_text)
        self.assertIn("GEM/2026/B/1234567", pdf_text)
        self.assertIn("Special eligibility", pdf_text)
        self.assertIn("Authorized Signatory", pdf_text)
        self.assertIn("Company Seal and Stamp", pdf_text)

        prepare_page = self.client.get(reverse("bid-prepare", args=[self.bid.pk]))
        self.assertContains(prepare_page, "Special Eligibility Certificate")
        self.assertContains(prepare_page, "Download PDF")
        self.assertContains(prepare_page, "Delete custom PDF")

        live_preview = self.client.post(
            reverse("generated-document-preview", args=[document.pk]),
            {"editable_content": "Live preview content"},
        )
        self.assertEqual(live_preview.status_code, 200)
        self.assertEqual(live_preview["Content-Type"], "application/pdf")
        self.assertEqual(live_preview["X-Frame-Options"], "SAMEORIGIN")
        self.assertIn("Live preview content", self.pdf_text(live_preview.content))

    def test_builtin_generate_action_does_not_require_custom_template_fields(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("bid-prepare", args=[self.bid.pk]), {
            "action": "generate:experience_declaration",
            "boq-TOTAL_FORMS": "0",
            "boq-INITIAL_FORMS": "0",
            "boq-MIN_NUM_FORMS": "0",
            "boq-MAX_NUM_FORMS": "1000",
        })

        document = GeneratedDocument.objects.get(bid=self.bid, document_type="experience_declaration")
        self.assertRedirects(response, reverse("generated-document-edit", args=[document.pk]))
        custom_form = CustomDocumentForm()
        self.assertFalse(custom_form.fields["title"].required)
        self.assertFalse(custom_form.fields["content"].required)

    def test_regenerating_builtin_document_preserves_saved_template_edits(self):
        self.client.force_login(self.user)
        document = GeneratedDocument.objects.create(
            bid=self.bid,
            document_type="experience_declaration",
            title="Experience Declaration",
            editable_content=(
                "EXPERIENCE DECLARATION\n\n"
                "Saved declaration body that the user edited.\n\n"
                "Signature:"
            ),
            template_version="2.5",
            generated_by=self.user,
        )

        response = self.client.post(reverse("bid-prepare", args=[self.bid.pk]), {
            "action": "generate:experience_declaration",
            "boq-TOTAL_FORMS": "0",
            "boq-INITIAL_FORMS": "0",
            "boq-MIN_NUM_FORMS": "0",
            "boq-MAX_NUM_FORMS": "1000",
        })

        self.assertRedirects(response, reverse("generated-document-edit", args=[document.pk]))
        document.refresh_from_db()
        self.assertIn("Saved declaration body that the user edited.", document.editable_content)
        pdf = self.client.get(reverse("generated-document-view", args=[document.pk]))
        self.assertIn("Saved declaration body that the user edited.", self.pdf_text(pdf.content))

    def test_custom_pdf_can_be_deleted_and_legacy_file_is_cleaned_up(self):
        document = GeneratedDocument.objects.create(
            bid=self.bid,
            document_type="custom_special_certificate",
            title="Special Eligibility Certificate",
            editable_content="Custom text",
            generated_by=self.user,
        )
        document.file.save("custom-certificate.pdf", ContentFile(b"%PDF-1.4\ncustom pdf"), save=True)
        file_name = document.file.name
        self.client.force_login(self.user)

        response = self.client.post(reverse("generated-document-delete", args=[document.pk]))

        self.assertRedirects(response, reverse("bid-prepare", args=[self.bid.pk]))
        self.assertFalse(GeneratedDocument.objects.filter(pk=document.pk).exists())
        self.assertFalse(document.file.storage.exists(file_name))

        standard_document = GeneratedDocument.objects.create(
            bid=self.bid,
            document_type="experience_declaration",
            title="Experience Declaration",
            generated_by=self.user,
        )
        response = self.client.post(reverse("generated-document-delete", args=[standard_document.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(GeneratedDocument.objects.filter(pk=standard_document.pk).exists())

    def test_legacy_editor_upgrade_and_save_then_download_use_the_same_text(self):
        document = GeneratedDocument.objects.create(
            bid=self.bid,
            document_type="experience_declaration",
            title="Experience Declaration",
            editable_content="Legacy editable body",
            generated_by=self.user,
        )
        document.file.save("legacy-generated.pdf", ContentFile(b"%PDF-1.4\nlegacy generated file"), save=True)
        legacy_file_name = document.file.name
        image_data = io.BytesIO()
        Image.new("RGB", (20, 10), color="blue").save(image_data, format="PNG")
        self.profile.signature_image.save("signature.png", ContentFile(image_data.getvalue()), save=False)
        self.profile.stamp_image.save("stamp.png", ContentFile(image_data.getvalue()), save=False)
        self.profile.save()
        self.client.force_login(self.user)
        editor_url = reverse("generated-document-edit", args=[document.pk])
        response = self.client.get(editor_url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "GeM Bid No.: GEM/2026/B/1234567")
        self.assertContains(response, "Authorized Signatory")
        self.assertContains(response, "signature and stamp are image files")
        self.assertNotContains(response, "Placed in the PDF at the signature line")
        self.assertNotContains(response, "This preview shows the saved signature and stamp positions")
        document.refresh_from_db()
        self.assertIn("Legacy editable body", document.editable_content)
        self.assertFalse(document.file)
        self.assertFalse(document.file.storage.exists(legacy_file_name))

        edited_text = "Edited PDF title\n\nCustom clause the user added\n\nSignature:\n\nPlace: Patna, Bihar"
        response = self.client.post(editor_url, {
            "editable_content": edited_text,
            "download_after_save": "1",
        })
        self.assertRedirects(response, f"{reverse('generated-document-view', args=[document.pk])}?download=1")
        document.refresh_from_db()
        self.assertTrue(document.editable_content.startswith("Edited PDF title\n\nCustom clause the user added"))
        self.assertIn("Company Seal and Stamp", document.editable_content)
        download = self.client.get(reverse("generated-document-view", args=[document.pk]), {"download": "1"})
        pdf_text = self.pdf_text(download.content)
        self.assertIn("Custom clause the user added", pdf_text)
        self.assertNotIn("Legacy editable body", pdf_text)
        self.assertFalse(document.file)

    def test_legacy_generated_document_preview_upgrades_to_letterhead(self):
        document = GeneratedDocument.objects.create(
            bid=self.bid,
            document_type="experience_declaration",
            title="Experience Declaration",
            editable_content=(
                "Experience Declaration\n\n"
                "Bid: GEM/2026/B/1234567    Title: Example OFC work\n\n"
                "Buyer: Example Buyer\n\n"
                "Bidder: Example Networks\n\n"
                "Preserved declaration body."
            ),
            template_version="1.5",
            generated_by=self.user,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("generated-document-view", args=[document.pk]))

        self.assertEqual(response.status_code, 200)
        pdf_text = self.pdf_text(response.content)
        self.assertIn("M/S EXAMPLE NETWORKS", pdf_text)
        self.assertNotIn("GeM Bid No.:", pdf_text)
        self.assertIn("GeM Bid No. GEM/2026/B/1234567", " ".join(pdf_text.split()))
        self.assertIn("Preserved declaration body.", pdf_text)
        self.assertIn("Company Seal and Stamp", pdf_text)
        self.assertNotIn("Bid: GEM/2026/B/1234567", pdf_text)
        document.refresh_from_db()
        self.assertEqual(document.template_version, "2.5")
        self.assertIn("M/S EXAMPLE NETWORKS", document.editable_content)
        self.assertIn("Company Seal and Stamp", document.editable_content)
        self.assertEqual(document.editable_content.count("Authorized Signatory"), 1)

    def test_previous_letterhead_is_simplified_and_footer_restored_when_pdf_is_upgraded(self):
        self.profile.legal_name = "Aniket Kumar"
        self.profile.address = "WARD-9, CHANDRABHAN TOLA, AUNTA MAIN ROAD, NEAR PRIYANKA STUDIO"
        self.profile.city = "Patna"
        self.profile.state = "Bihar"
        self.profile.pincode = "803303"
        self.profile.gstin = "10HKYPK5816H1ZS"
        self.profile.pan = "HKYPK5816H"
        self.profile.save()
        document = GeneratedDocument.objects.create(
            bid=self.bid,
            document_type="experience_declaration",
            title="Experience Declaration",
            editable_content=(
                "M/S ANIKET KUMAR\n"
                "WARD-9, CHANDRABHAN TOLA, AUNTA MAIN ROAD, NEAR PRIYANKA STUDIO, PATNA, BIHAR, 803303\n"
                "GSTIN: 10HKYPK5816H1ZS\nPAN: HKYPK5816H\n\n"
                "EXPERIENCE DECLARATION\n\n"
                "GeM Bid No.: GEM/2026/B/1234567\nDate: 05/10/26\n\n"
                "Preserved body.\n\n"
                "Declaration\nI/We declare that this document is true.\n\n"
                "Authorized Signatory\n\n"
                "Signature:                                      Company Seal and Stamp\n"
                "Name: Aniket Kumar\nDate: 05 October 2026\nPlace: Patna, Bihar"
            ),
            template_version="2.1",
            generated_by=self.user,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("generated-document-view", args=[document.pk]))

        self.assertEqual(response.status_code, 200)
        pdf_text = self.pdf_text(response.content)
        self.assertIn("AUNTA, PATNA, BIHAR, 803303", pdf_text)
        self.assertIn("GSTIN: 10HKYPK5816H1ZS", pdf_text)
        self.assertIn("Preserved body.", pdf_text)
        self.assertNotIn("WARD-9", pdf_text)
        self.assertNotIn("CHANDRABHAN", pdf_text)
        self.assertNotIn("MAIN ROAD", pdf_text)
        self.assertNotIn("PRIYANKA STUDIO", pdf_text)
        self.assertNotIn("PAN:", pdf_text)
        self.assertIn("Company Seal and Stamp", pdf_text)
        self.assertIn("Authorized Signatory", pdf_text)
        self.assertEqual(pdf_text.count("Authorized Signatory"), 1)
        document.refresh_from_db()
        self.assertEqual(document.template_version, "2.5")
        self.assertNotIn("PAN:", document.editable_content)
        self.assertIn("Company Seal and Stamp", document.editable_content)
        self.assertEqual(document.editable_content.count("Authorized Signatory"), 1)

    def test_existing_signatory_template_gets_current_date_after_signature(self):
        document = GeneratedDocument.objects.create(
            bid=self.bid,
            document_type="experience_declaration",
            title="Experience Declaration",
            editable_content="Authorized Signatory\nName: Aniket Kumar\nSignature:\nPlace: Patna, Bihar",
            template_version="1.4",
            generated_by=self.user,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("generated-document-edit", args=[document.pk]))

        self.assertEqual(response.status_code, 200)
        document.refresh_from_db()
        expected_date = f"Date: {timezone.localdate().strftime('%d %B %Y')}"
        self.assertEqual(document.editable_content.count("Date:"), 1)
        self.assertIn(expected_date, document.editable_content)
        self.assertLess(document.editable_content.index("Signature:"), document.editable_content.index(expected_date))
        self.assertLess(document.editable_content.rindex(expected_date), document.editable_content.index("Place:"))
        self.assertEqual(document.editable_content.count("Authorized Signatory"), 1)
        pdf_response = self.client.get(reverse("generated-document-view", args=[document.pk]))
        pdf_text = self.pdf_text(pdf_response.content)
        self.assertIn(expected_date, pdf_text)
        self.assertLess(pdf_text.index(expected_date), pdf_text.index("Place:"))
