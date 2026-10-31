from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from io import BytesIO
import math
import tempfile
import pymupdf
from PIL import Image, ImageDraw
from django.test import TestCase, override_settings
from django.urls import reverse
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas

from .models import CompanyDocument, CompanyProfile
from .signatures import stamp_image_bytes
from .self_attestation import self_attested_pdf
from apps.generation.services.pdf_documents import SignatureStampBlock


class CompanySignatureEditorTests(TestCase):
    def setUp(self):
        self.temp_media = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.temp_media.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(self.temp_media.cleanup)
        self.user = get_user_model().objects.create_user(username="signature-owner", password="test-password")
        self.client.force_login(self.user)

    def test_company_profile_renders_signature_editor(self):
        response = self.client.get("/companies/profile/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Signature and stamp editor")
        self.assertContains(response, "id_signature_rotation")
        self.assertContains(response, "id_stamp_rotation")
        self.assertContains(response, "id_stamp_scale")
        self.assertContains(response, "Stamp angle")
        self.assertContains(response, "drag it within the preview to set its position in the PDF")
        self.assertContains(response, 'id="signature-canvas" width="560" height="300"')
        self.assertContains(response, 'id="stamp-canvas" width="560" height="300"')
        self.assertContains(response, "Position signature and stamp in this PDF")
        self.assertContains(response, 'id="company-mark-position-canvas"')
        self.assertContains(response, 'id="company-signature-x"')
        self.assertContains(response, 'id="company-stamp-y"')
        self.assertContains(response, 'data-collapse-key="company-signature-document-options"')
        self.assertContains(response, 'data-start-collapsed="true"')
        self.assertContains(response, 'max="90"')
        self.assertContains(response, 'min="-90"')
        self.assertContains(response, "Add saved signature and stamp to these PDFs")
        self.assertContains(response, "MSME Turnover Exemption Declaration")
        self.assertContains(response, 'name="signature_document_types" value="msme_turnover_exemption"')
        self.assertContains(response, 'name="stamp_document_types" value="msme_turnover_exemption"')
        self.assertContains(response, "Add signature")
        self.assertContains(response, "Add stamp")
        self.assertContains(response, "Optional company stamp / seal")
        page = response.content.decode()
        general_profile_form = page.split('<input type="hidden" name="form_action" value="profile">', 1)[1].split('</form>', 1)[0]
        self.assertNotIn("stamp_rotation", general_profile_form)
        self.assertNotIn("stamp_scale", general_profile_form)
        self.assertEqual(page.count('name="stamp_rotation"'), 1)
        self.assertEqual(page.count('name="stamp_scale"'), 1)
        signature_start = page.index("01</span> Signature</legend>")
        stamp_start = page.index("02</span> Optional company stamp / seal</legend>")
        position_start = page.index("Position signature and stamp in this PDF")
        self.assertLess(stamp_start, position_start)
        control_order = (
            'for="id_signature_image"',
            'id="signature-canvas"',
            'for="id_signature_rotation"',
            'for="id_signature_scale"',
        )
        positions = []
        search_start = signature_start
        for control in control_order:
            search_start = page.index(control, search_start)
            positions.append(search_start)
        self.assertLess(positions[-1], stamp_start)
        stamp_controls = (
            'for="id_stamp_image"',
            'id="stamp-canvas"',
            'for="id_stamp_rotation"',
            'for="id_stamp_scale"',
        )
        search_start = stamp_start
        for control in stamp_controls:
            search_start = page.index(control, search_start)
            positions.append(search_start)
        self.assertEqual(positions, sorted(positions))

    def test_saved_editor_settings_control_signature_angle_size_and_pdf_types(self):
        response = self.client.post("/companies/profile/", {
            "form_action": "signature",
            "signature_style": "blue_ink",
            "signature_rotation": "6.0",
            "signature_scale": "1.20",
            "signature_document_types": ["experience_declaration", "boq_specifications"],
        })
        self.assertRedirects(response, "/companies/profile/")
        profile = CompanyProfile.objects.get(owner=self.user)
        self.assertEqual(str(profile.signature_rotation), "6.0")
        self.assertEqual(str(profile.signature_scale), "1.20")
        self.assertEqual(profile.signature_document_types, ["experience_declaration", "boq_specifications"])

    def test_dragged_signature_and_stamp_positions_are_saved(self):
        response = self.client.post("/companies/profile/", {
            "form_action": "signature",
            "signature_style": "blue_ink",
            "signature_rotation": "0",
            "signature_scale": "1",
            "stamp_rotation": "0",
            "stamp_scale": "1",
            "signature_position_x": "54.25",
            "signature_position_y": "38.50",
            "stamp_position_x": "31.75",
            "stamp_position_y": "62.25",
            "signature_document_types": ["experience_declaration"],
        })
        self.assertRedirects(response, "/companies/profile/")
        profile = CompanyProfile.objects.get(owner=self.user)
        self.assertEqual(str(profile.signature_position_x), "54.25")
        self.assertEqual(str(profile.signature_position_y), "38.50")
        self.assertEqual(str(profile.stamp_position_x), "31.75")
        self.assertEqual(str(profile.stamp_position_y), "62.25")

        response = self.client.get("/companies/profile/")
        self.assertContains(response, 'data-position-x="54.25"')
        self.assertContains(response, 'data-position-y="38.50"')
        self.assertContains(response, 'data-position-x="31.75"')
        self.assertContains(response, 'data-position-y="62.25"')

    def test_stamp_angle_and_size_are_saved(self):
        response = self.client.post("/companies/profile/", {
            "form_action": "signature",
            "signature_style": "blue_ink",
            "signature_rotation": "0",
            "signature_scale": "1",
            "stamp_rotation": "35.5",
            "stamp_scale": "1.25",
            "signature_document_types": ["experience_declaration"],
        })
        self.assertRedirects(response, "/companies/profile/")
        profile = CompanyProfile.objects.get(owner=self.user)
        self.assertEqual(str(profile.stamp_rotation), "35.5")
        self.assertEqual(str(profile.stamp_scale), "1.25")

    def test_stamp_rotation_changes_rendered_image_orientation(self):
        image = Image.new("RGBA", (180, 100), (0, 0, 0, 0))
        ImageDraw.Draw(image).line((20, 50, 160, 50), fill=(20, 40, 180, 255), width=7)
        image_data = BytesIO()
        image.save(image_data, format="PNG")
        profile = CompanyProfile.objects.create(owner=self.user, stamp_rotation=30)
        profile.stamp_image.save(
            "seal.png",
            SimpleUploadedFile("seal.png", image_data.getvalue(), content_type="image/png"),
        )

        stamp_pdf_bytes = stamp_image_bytes(profile)
        with Image.open(BytesIO(stamp_pdf_bytes)) as rendered_stamp:
            alpha = rendered_stamp.getchannel("A")
            points = [
                (x, y)
                for y in range(rendered_stamp.height)
                for x in range(rendered_stamp.width)
                if alpha.getpixel((x, y)) > 0
            ]
        mean_x = sum(x for x, _ in points) / len(points)
        mean_y = sum(y for _, y in points) / len(points)
        covariance_xx = sum((x - mean_x) ** 2 for x, _ in points)
        covariance_yy = sum((y - mean_y) ** 2 for _, y in points)
        covariance_xy = sum((x - mean_x) * (y - mean_y) for x, y in points)
        rendered_angle = 0.5 * math.degrees(math.atan2(2 * covariance_xy, covariance_xx - covariance_yy))
        self.assertAlmostEqual(rendered_angle, 30, delta=5)

    def test_stamp_image_removes_white_box_and_crops_to_stamp_artwork(self):
        image = Image.new("RGB", (180, 100), "white")
        ImageDraw.Draw(image).ellipse((35, 15, 145, 85), outline=(190, 25, 35), width=8)
        image_data = BytesIO()
        image.save(image_data, format="PNG")
        profile = CompanyProfile.objects.create(owner=self.user)
        profile.stamp_image.save(
            "white-background-seal.png",
            SimpleUploadedFile(
                "white-background-seal.png",
                image_data.getvalue(),
                content_type="image/png",
            ),
        )

        stamp_data = stamp_image_bytes(profile)
        with Image.open(BytesIO(stamp_data)) as rendered_stamp:
            rendered_stamp = rendered_stamp.convert("RGBA")
            self.assertLess(rendered_stamp.width, 180)
            self.assertLess(rendered_stamp.height, 100)
            self.assertEqual(rendered_stamp.getpixel((0, 0))[3], 0)
            self.assertTrue(any(
                alpha > 0 and red > green * 2 and red > blue * 2
                for red, green, blue, alpha in rendered_stamp.getdata()
            ))

    def test_editor_signature_endpoint_returns_unrotated_image_for_canvas(self):
        image = Image.new("RGB", (240, 80), "white")
        ImageDraw.Draw(image).line((20, 40, 220, 40), fill=(15, 35, 190), width=8)
        image_data = BytesIO()
        image.save(image_data, format="PNG")
        profile = CompanyProfile.objects.create(owner=self.user, signature_rotation=30)
        profile.signature_image.save(
            "signature.png",
            SimpleUploadedFile("signature.png", image_data.getvalue(), content_type="image/png"),
            save=True,
        )

        editor_response = self.client.get("/companies/profile/signature/?editor=1&preview=123")
        self.assertEqual(editor_response.status_code, 200)
        with Image.open(BytesIO(editor_response.content)) as editor_image:
            editor_image = editor_image.convert("RGBA")
            editor_alpha = editor_image.getchannel("A")
            editor_points = [
                (x, y)
                for y in range(editor_image.height)
                for x in range(editor_image.width)
                if editor_alpha.getpixel((x, y)) > 0
            ]

        mean_x = sum(x for x, _ in editor_points) / len(editor_points)
        mean_y = sum(y for _, y in editor_points) / len(editor_points)
        covariance_xx = sum((x - mean_x) ** 2 for x, _ in editor_points)
        covariance_yy = sum((y - mean_y) ** 2 for _, y in editor_points)
        covariance_xy = sum((x - mean_x) * (y - mean_y) for x, y in editor_points)
        editor_angle = 0.5 * math.degrees(math.atan2(2 * covariance_xy, covariance_xx - covariance_yy))
        self.assertAlmostEqual(editor_angle, 0, delta=5)

    def test_stamp_scale_changes_generated_pdf_stamp_dimensions(self):
        image_data = BytesIO()
        Image.new("RGBA", (180, 100), "blue").save(image_data, format="PNG")
        stamp = image_data.getvalue()

        normal = SignatureStampBlock(stamp, b"", signature_scale=1, stamp_scale=1)
        larger = SignatureStampBlock(stamp, b"", signature_scale=1, stamp_scale=1.5)

        self.assertAlmostEqual(normal.stamp_size[0], 26 * mm)
        self.assertAlmostEqual(larger.stamp_size[0], 39 * mm)
        self.assertAlmostEqual(larger.width / normal.width, 1.0)
        self.assertGreater(larger.stamp_size[1], normal.stamp_size[1])

    def test_saved_positions_are_used_in_self_attested_company_document(self):
        signature = Image.new("RGB", (240, 80), "white")
        ImageDraw.Draw(signature).line((20, 40, 220, 40), fill=(15, 35, 190), width=8)
        signature_data = BytesIO()
        signature.save(signature_data, format="PNG")
        self.profile = CompanyProfile.objects.create(owner=self.user)
        self.profile.signature_image.save(
            "attested-signature.png",
            SimpleUploadedFile("attested-signature.png", signature_data.getvalue(), content_type="image/png"),
            save=True,
        )
        stamp_data = BytesIO()
        Image.new("RGBA", (180, 100), (200, 20, 20, 255)).save(stamp_data, format="PNG")
        self.profile.stamp_image.save(
            "attested-stamp.png",
            SimpleUploadedFile("attested-stamp.png", stamp_data.getvalue(), content_type="image/png"),
            save=True,
        )
        source_pdf = BytesIO()
        writer = pdf_canvas.Canvas(source_pdf)
        writer.drawString(100, 200, "Signature:")
        writer.save()
        document = CompanyDocument.objects.create(
            company=self.profile,
            title="Signed source",
            document_type=CompanyDocument.DocumentType.OTHER,
            include_signature=True,
            include_stamp=True,
        )
        document.file.save(
            "source.pdf",
            SimpleUploadedFile("source.pdf", source_pdf.getvalue(), content_type="application/pdf"),
            save=True,
        )

        def centers(pdf_data):
            result = {}
            with pymupdf.open(stream=pdf_data, filetype="pdf") as pdf:
                for xref, *_rest in pdf[0].get_images(full=True):
                    info = pdf.extract_image(xref)
                    with Image.open(BytesIO(info["image"])) as image:
                        pixels = list(image.convert("RGBA").getdata())
                    red_pixels = sum(red > blue + 40 and red > green + 40 for red, green, blue, alpha in pixels if alpha)
                    blue_pixels = sum(blue > red + 40 and blue > green + 40 for red, green, blue, alpha in pixels if alpha)
                    mark = "stamp" if red_pixels > blue_pixels else "signature"
                    rect = pdf[0].get_image_rects(xref)[0]
                    result[mark] = {
                        "center": ((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2),
                        "width": rect.width,
                        "height": rect.height,
                    }
            return result

        initial_pdf = self_attested_pdf(document, self.profile)
        initial = centers(initial_pdf)
        initial_x = {
            "signature": float(self.profile.signature_position_x),
            "stamp": float(self.profile.stamp_position_x),
        }
        initial_y = {
            "signature": float(self.profile.signature_position_y),
            "stamp": float(self.profile.stamp_position_y),
        }
        self.profile.signature_position_x = "54.25"
        self.profile.signature_position_y = "38.50"
        self.profile.stamp_position_x = "31.75"
        self.profile.stamp_position_y = "62.25"
        self.profile.save()
        moved = centers(self_attested_pdf(document, self.profile))

        def clamped_delta(area, mark_size, old_position, new_position):
            low, high = mark_size / 2, area - mark_size / 2
            old_center = min(max(old_position / 100 * area, low), high)
            new_center = min(max(new_position / 100 * area, low), high)
            return new_center - old_center

        with pymupdf.open(stream=initial_pdf, filetype="pdf") as pdf:
            area_width = pdf[0].rect.width - 40 * mm
        area_height = 30 * mm * max(
            float(self.profile.signature_scale), float(self.profile.stamp_scale), 1
        )
        for mark, old_x, old_y, new_x, new_y in (
            ("signature", initial_x["signature"], initial_y["signature"], 54.25, 38.50),
            ("stamp", initial_x["stamp"], initial_y["stamp"], 31.75, 62.25),
        ):
            self.assertAlmostEqual(
                moved[mark]["center"][0] - initial[mark]["center"][0],
                clamped_delta(area_width, initial[mark]["width"], old_x, new_x),
                delta=1,
            )
            self.assertAlmostEqual(
                moved[mark]["center"][1] - initial[mark]["center"][1],
                clamped_delta(area_height, initial[mark]["height"], old_y, new_y),
                delta=1,
            )

    def test_supporting_document_signature_and_stamp_choices_are_independent(self):
        self.profile = CompanyProfile.objects.create(owner=self.user)
        stamp_data = BytesIO()
        Image.new("RGBA", (80, 80), (210, 20, 20, 255)).save(stamp_data, format="PNG")
        self.profile.stamp_image.save(
            "red-stamp.png",
            SimpleUploadedFile("red-stamp.png", stamp_data.getvalue(), content_type="image/png"),
            save=True,
        )
        source_pdf = BytesIO()
        writer = pdf_canvas.Canvas(source_pdf)
        writer.drawString(100, 200, "Signature:")
        writer.save()
        document = CompanyDocument.objects.create(
            company=self.profile,
            title="Stamp-only source",
            document_type=CompanyDocument.DocumentType.OTHER,
            include_signature=False,
            include_stamp=False,
        )
        document.file.save(
            "stamp-only.pdf",
            SimpleUploadedFile("stamp-only.pdf", source_pdf.getvalue(), content_type="application/pdf"),
            save=True,
        )
        response = self.client.get("/companies/profile/")
        self.assertContains(response, 'name="include_signature"')
        self.assertContains(response, 'name="include_stamp"')
        self.assertContains(response, "Add stamp")

        response = self.client.post("/companies/profile/", {
            "form_action": "document_marks",
            "document_id": document.pk,
            "include_stamp": "on",
        })
        self.assertRedirects(response, "/companies/profile/")
        document.refresh_from_db()
        self.assertFalse(document.include_signature)
        self.assertTrue(document.include_stamp)

        signed_copy = self.client.get(
            reverse("company-document-view", args=[document.pk]),
            {"self_attest": "1"},
        )
        self.assertEqual(signed_copy.status_code, 200)
        with pymupdf.open(stream=signed_copy.content, filetype="pdf") as pdf:
            images = pdf[0].get_images(full=True)
            self.assertEqual(len(images), 1)
            image_data = pdf.extract_image(images[0][0])["image"]
        with Image.open(BytesIO(image_data)) as stamp_image:
            red, green, blue, _alpha = stamp_image.convert("RGBA").getpixel((0, 0))
        self.assertGreater(red, green)
        self.assertGreater(red, blue)

    def test_signature_rotation_accepts_90_degrees_and_rejects_greater_values(self):
        response = self.client.post("/companies/profile/", {
            "form_action": "signature",
            "signature_style": "blue_ink",
            "signature_rotation": "90",
            "signature_scale": "1.0",
            "signature_document_types": ["experience_declaration"],
        })
        self.assertRedirects(response, "/companies/profile/")
        profile = CompanyProfile.objects.get(owner=self.user)
        self.assertEqual(str(profile.signature_rotation), "90.0")

        response = self.client.post("/companies/profile/", {
            "form_action": "signature",
            "signature_style": "blue_ink",
            "signature_rotation": "90.5",
            "signature_scale": "1.0",
            "signature_document_types": ["experience_declaration"],
        })
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context["signature_form"], "signature_rotation", "Ensure this value is less than or equal to 90.")
        profile.refresh_from_db()
        self.assertEqual(str(profile.signature_rotation), "90.0")

    def test_stamp_rotation_rejects_values_greater_than_90_degrees(self):
        response = self.client.post("/companies/profile/", {
            "form_action": "signature",
            "signature_style": "blue_ink",
            "signature_rotation": "0",
            "signature_scale": "1",
            "stamp_rotation": "90.5",
            "stamp_scale": "1",
            "signature_document_types": ["experience_declaration"],
        })
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context["signature_form"], "stamp_rotation", "Ensure this value is less than or equal to 90.")
        profile = CompanyProfile.objects.get(owner=self.user)
        self.assertEqual(str(profile.stamp_rotation), "0.0")

    def test_stamp_upload_is_optional_and_saved_for_reuse(self):
        image = Image.new("RGB", (180, 100), "white")
        ImageDraw.Draw(image).ellipse((20, 10, 160, 90), outline=(20, 20, 160), width=5)
        stream = BytesIO()
        image.save(stream, format="PNG")
        response = self.client.post("/companies/profile/", {
            "form_action": "signature",
            "signature_style": "blue_ink",
            "signature_rotation": "0",
            "signature_scale": "1",
            "signature_document_types": ["experience_declaration"],
            "stamp_image": SimpleUploadedFile("seal.png", stream.getvalue(), content_type="image/png"),
        })
        self.assertRedirects(response, "/companies/profile/")
        profile = CompanyProfile.objects.get(owner=self.user)
        self.assertTrue(profile.stamp_image)
