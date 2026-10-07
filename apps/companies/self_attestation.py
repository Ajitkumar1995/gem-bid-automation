from io import BytesIO
import pymupdf
from PIL import Image
from reportlab.lib.units import mm

from .signatures import stamp_image_bytes, styled_signature


def _scaled_image_size(image_data, max_width, max_height, scale):
    with Image.open(BytesIO(image_data)) as image:
        image_width, image_height = image.size
    factor = min(max_width / image_width, max_height / image_height, 1) * scale
    return image_width * factor, image_height * factor


def self_attested_pdf(document, profile):
    """Build a signed copy of a supported PDF/image; never modifies source."""
    with document.file.open("rb") as source:
        raw = source.read()
    if raw.startswith(b"%PDF-"):
        pdf = pymupdf.open(stream=raw, filetype="pdf")
    else:
        image = Image.open(BytesIO(raw)).convert("RGB")
        page = pymupdf.open()
        rect = pymupdf.Rect(0, 0, image.width, image.height)
        p = page.new_page(width=image.width, height=image.height)
        encoded = BytesIO()
        image.save(encoded, format="PNG")
        p.insert_image(rect, stream=encoded.getvalue())
        pdf = page
    sig = styled_signature(profile) if document.include_signature else b""
    stamp = stamp_image_bytes(profile) if document.include_stamp else b""
    for page in pdf:
        rect = page.rect
        if sig or stamp:
            anchors = []
            for label in ("Authorized signature", "Signature with Date", "Signature:", "Signature"):
                anchors.extend(page.search_for(label))
            anchor = max(anchors, key=lambda item: item.y0) if anchors else None
            signature_scale = float(profile.signature_scale or 1)
            stamp_scale = float(profile.stamp_scale or 1)
            frame_scale = max(signature_scale, stamp_scale, 1)
            area_width, area_height = rect.width - 40 * mm, 30 * mm * frame_scale
            area_left = (rect.width - area_width) / 2
            area_right = area_left + area_width
            # Keep the ink below the existing signature label instead of
            # covering the label or any adjacent declaration text.
            area_top = anchor.y1 + 2 if anchor else rect.height - area_height - 30
            area_top = min(max(12, area_top), rect.height - area_height - 8)

            def position_in_area(x_percent, y_percent, width, height):
                center_x = area_left + float(x_percent) / 100 * area_width
                center_y = area_top + float(y_percent) / 100 * area_height
                x0 = min(max(area_left, center_x - width / 2), area_right - width)
                y0 = min(max(area_top, center_y - height / 2), area_top + area_height - height)
                return x0, y0

            if sig:
                width, height = _scaled_image_size(
                    sig,
                    38 * mm,
                    30 * mm,
                    signature_scale,
                )
                x0, y0 = position_in_area(
                    profile.signature_position_x,
                    profile.signature_position_y,
                    width,
                    height,
                )
                page.insert_image(pymupdf.Rect(x0, y0, x0 + width, y0 + height), stream=sig, keep_proportion=True, overlay=True)
            if stamp:
                stamp_width, stamp_height = _scaled_image_size(
                    stamp,
                    26 * mm,
                    20 * mm,
                    stamp_scale,
                )
                stamp_x0, stamp_y0 = position_in_area(
                    profile.stamp_position_x,
                    profile.stamp_position_y,
                    stamp_width,
                    stamp_height,
                )
                page.insert_image(pymupdf.Rect(stamp_x0, stamp_y0, stamp_x0 + stamp_width, stamp_y0 + stamp_height), stream=stamp, keep_proportion=True, overlay=True)
    result = pdf.tobytes(garbage=3, deflate=True)
    pdf.close()
    return result
