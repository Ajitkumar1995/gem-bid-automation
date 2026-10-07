from io import BytesIO

from PIL import Image, ImageChops


def styled_signature(profile):
    """Extract the uploaded blue pen strokes and remove the photo paper background."""
    if not profile.signature_image:
        return b""
    with profile.signature_image.open("rb") as source:
        image = Image.open(source).convert("RGBA")
    style = getattr(profile, "signature_style", "blue_ink")
    ink_color = (12, 35, 170) if style != "black_ink" else (20, 20, 24)
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            r, g, b, old_alpha = pixels[x, y]
            # The supplied photo has gray paper and blue ink. Chroma isolates
            # the pen while discarding paper shadows and texture.
            blue_strength = b - max(r, g)
            ink_alpha = max(0, min(255, (blue_strength - 10) * 4))
            ink_alpha = (ink_alpha * old_alpha) // 255
            if ink_alpha < 18:
                ink_alpha = 0
            pixels[x, y] = (*ink_color, ink_alpha)
    bbox = image.getchannel("A").getbbox()
    if bbox:
        left, top, right, bottom = bbox
        padding = 8
        image = image.crop((max(0, left-padding), max(0, top-padding), min(image.width, right+padding), min(image.height, bottom+padding)))
    rotation = float(getattr(profile, "signature_rotation", 0) or 0)
    if rotation:
        image = image.rotate(-rotation, expand=True, resample=Image.Resampling.BICUBIC)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def stamp_image_bytes(profile):
    if not profile.stamp_image:
        return b""
    with profile.stamp_image.open("rb") as source:
        image = Image.open(source).convert("RGBA")
    red, green, blue, original_alpha = image.split()
    darkest = ImageChops.darker(ImageChops.darker(red, green), blue)
    brightest = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    color_spread = ImageChops.subtract(brightest, darkest)
    colored_ink = Image.eval(color_spread, lambda value: 255 if value > 45 else 0)
    neutral_ink = Image.eval(
        darkest,
        lambda value: (
            255 if value <= 190
            else 0 if value >= 235
            else int((235 - value) * 255 / 45)
        ),
    )
    alpha = ImageChops.multiply(
        original_alpha,
        ImageChops.lighter(colored_ink, neutral_ink),
    )
    alpha = alpha.point(lambda value: 0 if value < 12 else value)
    image.putalpha(alpha)
    bbox = alpha.getbbox()
    if bbox:
        left, top, right, bottom = bbox
        padding = 6
        image = image.crop((
            max(0, left - padding),
            max(0, top - padding),
            min(image.width, right + padding),
            min(image.height, bottom + padding),
        ))
    rotation = float(getattr(profile, "stamp_rotation", 0) or 0)
    if rotation:
        image = image.rotate(-rotation, expand=True, resample=Image.Resampling.BICUBIC)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
