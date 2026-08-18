"""Drawing primitives shared by every card layout.

Everything here works on an RGB canvas with an RGBA draw context
(`ImageDraw.Draw(image, "RGBA")`), so translucent panels blend without an
extra compositing pass.
"""

from collections.abc import Sequence
from typing import Literal

import qrcode  # type: ignore[import-untyped]
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from .fonts import Typeface, get_font
from .icons import draw_icon
from .palette import RGB, RGBA, Theme, darken, mix, readable_text, with_alpha

Align = Literal["left", "center", "right"]

Box = tuple[int, int, int, int]

# The dark ground the card sits on. Cards have rounded corners, and this is
# what shows through them - a near black rather than pure black so the corner
# reads as a card edge instead of a hole punched in the image.
PAGE_TINT = 0.72


def new_canvas(size: tuple[int, int], theme: Theme, *, inset: int = 0, radius: int = 0) -> Image.Image:
    """Gradient background with a couple of soft accent glows.

    With `inset` the gradient becomes a rounded card floating on a darker
    page, which is what gives every card its outline.
    """
    surface = vertical_gradient(size, theme.background_top, theme.background_bottom)
    width, height = size
    radial_glow(surface, (int(width * 0.86), int(height * 0.06)), int(width * 0.62), theme.accent, 78)
    radial_glow(surface, (int(width * -0.08), int(height * 0.58)), int(width * 0.55), theme.accent, 40)

    if inset <= 0:
        return surface

    page = Image.new("RGB", size, darken(theme.background_bottom, PAGE_TINT))
    page.paste(surface, (0, 0), rounded_mask(size, radius, inset))
    return page


def rounded_mask(size: tuple[int, int], radius: int, inset: int = 0) -> Image.Image:
    """Antialiased rounded rectangle mask, drawn at 4x and scaled down."""
    scale = 4
    width, height = size
    mask = Image.new("L", (width * scale, height * scale), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (inset * scale, inset * scale, (width - inset) * scale - 1, (height - inset) * scale - 1),
        radius=radius * scale,
        fill=255,
    )
    return mask.resize(size, Image.Resampling.LANCZOS)


def card_border(draw: ImageDraw.ImageDraw, size: tuple[int, int], radius: int, inset: int, color: RGB) -> None:
    """The accent outline around a card."""
    width, height = size
    draw.rounded_rectangle(
        (inset, inset, width - inset - 1, height - inset - 1),
        radius=radius,
        outline=with_alpha(color, 255),
        width=max(round(width / 360), 2),
    )


def vertical_gradient(size: tuple[int, int], top: RGB, bottom: RGB) -> Image.Image:
    """Rendered one pixel wide and stretched, which is far cheaper than
    drawing every row at full width."""
    width, height = size
    column = Image.new("RGB", (1, height))
    pixels = column.load()
    assert pixels is not None

    span = max(height - 1, 1)
    for y in range(height):
        ratio = y / span
        pixels[0, y] = (
            round(top[0] + (bottom[0] - top[0]) * ratio),
            round(top[1] + (bottom[1] - top[1]) * ratio),
            round(top[2] + (bottom[2] - top[2]) * ratio),
        )

    return column.resize((width, height), Image.Resampling.BILINEAR)


def radial_glow(image: Image.Image, center: tuple[int, int], radius: int, color: RGB, opacity: int) -> None:
    """Blurred circle of light, blurred at quarter scale for speed."""
    scale = 4
    width, height = image.size
    small = Image.new("L", (max(width // scale, 1), max(height // scale, 1)), 0)

    center_x, center_y = center[0] // scale, center[1] // scale
    small_radius = max(radius // scale, 1)
    ImageDraw.Draw(small).ellipse(
        (center_x - small_radius, center_y - small_radius, center_x + small_radius, center_y + small_radius),
        fill=opacity,
    )
    small = small.filter(ImageFilter.GaussianBlur(small_radius / 2))

    image.paste(Image.new("RGB", image.size, color), (0, 0), small.resize(image.size, Image.Resampling.BILINEAR))


def panel(draw: ImageDraw.ImageDraw, box: Box, radius: int, fill: RGBA, outline: RGBA | None = None) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=2 if outline else 0)


def text_width(draw: ImageDraw.ImageDraw, text: str, typeface: Typeface) -> float:
    return draw.textlength(text, font=typeface.font)


def tracked_width(draw: ImageDraw.ImageDraw, text: str, typeface: Typeface, tracking: float) -> float:
    return text_width(draw, text, typeface) + tracking * max(len(text) - 1, 0)


def tracked_text(
    draw: ImageDraw.ImageDraw,
    origin: tuple[float, float],
    text: str,
    typeface: Typeface,
    fill: RGB | RGBA,
    *,
    tracking: float,
) -> float:
    """Draw `text` with extra space between glyphs, one character at a time.

    Pillow has no letter spacing, and the small uppercase labels this design
    leans on ("SCAN TO JOIN THE SQUAD") look like a mistake set solid. Returns
    the x coordinate after the last glyph.
    """
    x, y = origin
    for character in text:
        draw.text((x, y), character, font=typeface.font, fill=fill)
        x += draw.textlength(character, font=typeface.font) + tracking
    return x - tracking if text else x


def ellipsize(draw: ImageDraw.ImageDraw, text: str, typeface: Typeface, max_width: float) -> str:
    if text_width(draw, text, typeface) <= max_width:
        return text

    trimmed = text
    while trimmed and text_width(draw, trimmed + "…", typeface) > max_width:
        trimmed = trimmed[:-1]
    return (trimmed.rstrip() + "…") if trimmed else ""


def wrap_text(draw: ImageDraw.ImageDraw, text: str, typeface: Typeface, max_width: float) -> list[str]:
    """Greedy word wrap. Words that are wider than the line get hard split so a
    pasted URL cannot blow out the layout."""
    lines: list[str] = []

    for paragraph in text.splitlines():
        if not paragraph.strip():
            continue

        current = ""
        for word in paragraph.split():
            candidate = f"{current} {word}".strip()
            if text_width(draw, candidate, typeface) <= max_width or not current:
                current = candidate
                while text_width(draw, current, typeface) > max_width and len(current) > 1:
                    cut = len(current) - 1
                    while cut > 1 and text_width(draw, current[:cut], typeface) > max_width:
                        cut -= 1
                    lines.append(current[:cut])
                    current = current[cut:]
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)

    return lines


def fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    sizes: Sequence[int],
    weight: Literal["regular", "bold"],
    max_width: float,
    max_lines: int,
) -> tuple[Typeface, list[str]]:
    """Pick the largest size from `sizes` that fits `text` in `max_lines`.

    Falls back to the smallest size with the last line ellipsized, so long
    display names shrink instead of overflowing.
    """
    typeface = get_font(sizes[-1], weight)
    lines: list[str] = []

    for size in sizes:
        typeface = get_font(size, weight)
        lines = wrap_text(draw, text, typeface, max_width)
        if len(lines) <= max_lines:
            return typeface, lines

    kept = lines[:max_lines]
    if kept:
        kept[-1] = ellipsize(draw, kept[-1] + "…", typeface, max_width)
    return typeface, kept


def draw_lines(
    draw: ImageDraw.ImageDraw,
    origin: tuple[int, int],
    lines: Sequence[str],
    typeface: Typeface,
    fill: RGB,
    *,
    align: Align = "left",
    max_width: float = 0,
    spacing: float = 1.0,
) -> int:
    """Draw pre-wrapped lines and return the y coordinate just below them."""
    x, y = origin
    step = round(typeface.line_height * spacing)

    for line in lines:
        offset = 0.0
        if align != "left" and max_width:
            slack = max_width - text_width(draw, line, typeface)
            offset = slack / 2 if align == "center" else slack
        draw.text((x + offset, y), line, font=typeface.font, fill=fill)
        y += step

    return y


def chip(
    draw: ImageDraw.ImageDraw,
    origin: tuple[int, int],
    text: str,
    typeface: Typeface,
    *,
    fill: RGBA,
    text_color: RGB,
    padding: tuple[int, int] = (24, 12),
    outline: RGBA | None = None,
    icon: str | None = None,
    tracking: float = 0.0,
) -> tuple[int, int]:
    """Rounded pill with centred text and an optional leading icon.

    Returns its (width, height) so a row of pills can advance the cursor.
    """
    pad_x, pad_y = padding
    label_width = tracked_width(draw, text, typeface, tracking)
    icon_size = round(typeface.size * 1.05) if icon else 0
    icon_gap = round(typeface.size * 0.42) if icon else 0

    width = round(label_width) + pad_x * 2 + icon_size + icon_gap
    height = typeface.line_height + pad_y * 2
    x, y = origin

    draw.rounded_rectangle(
        (x, y, x + width, y + height),
        radius=height // 2,
        fill=fill,
        outline=outline,
        width=2 if outline else 0,
    )

    text_x = x + pad_x
    if icon:
        icon_top = y + (height - icon_size) / 2
        draw_icon(draw, icon, (text_x, icon_top, text_x + icon_size, icon_top + icon_size), text_color)
        text_x += icon_size + icon_gap

    tracked_text(draw, (text_x, y + pad_y), text, typeface, text_color, tracking=tracking)
    return width, height


def icon_row_width(
    draw: ImageDraw.ImageDraw,
    entries: Sequence[tuple[str | None, str]],
    typeface: Typeface,
    *,
    icon_size: int,
    gap: int,
    spacing: int,
) -> float:
    """Measured width of `icon_row`, for centring it."""
    total = 0.0
    for index, (icon, label) in enumerate(entries):
        if index:
            total += spacing
        if icon:
            total += icon_size + gap
        total += text_width(draw, label, typeface)
    return total


def icon_row(
    draw: ImageDraw.ImageDraw,
    origin: tuple[float, float],
    entries: Sequence[tuple[str | None, str]],
    typeface: Typeface,
    fill: RGB,
    *,
    icon_size: int,
    gap: int,
    spacing: int,
    icon_fill: RGB | None = None,
) -> float:
    """A run of `icon + label` pairs on one baseline, e.g. the meta line under
    a squad title. Returns the x coordinate after the last label."""
    x, y = origin
    for index, (icon, label) in enumerate(entries):
        if index:
            x += spacing
        if icon:
            icon_top = y + (typeface.line_height - icon_size) / 2
            draw_icon(draw, icon, (x, icon_top, x + icon_size, icon_top + icon_size), icon_fill or fill)
            x += icon_size + gap
        draw.text((x, y), label, font=typeface.font, fill=fill)
        x += text_width(draw, label, typeface)
    return x


def circle_image(source: Image.Image, size: int) -> Image.Image:
    """Centre cropped circular thumbnail with an antialiased edge."""
    supersample = 4
    fitted = ImageOps.fit(source.convert("RGB"), (size, size), Image.Resampling.LANCZOS, centering=(0.5, 0.5))

    mask = Image.new("L", (size * supersample, size * supersample), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * supersample - 1, size * supersample - 1), fill=255)
    mask = mask.resize((size, size), Image.Resampling.LANCZOS)

    circle = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    circle.paste(fitted, (0, 0), mask)
    return circle


def initials_avatar(text: str, size: int, theme: Theme) -> Image.Image:
    """Stand in used when the payload carries no avatar."""
    initials = "".join(word[0] for word in text.split()[:2] if word).upper() or "?"

    tile = vertical_gradient((size, size), theme.accent, darken(theme.accent, 0.35))
    circle = circle_image(tile, size)

    draw = ImageDraw.Draw(circle, "RGBA")
    typeface = get_font(round(size * 0.40), "bold")
    label_width = text_width(draw, initials, typeface)
    draw.text(
        (size / 2 - label_width / 2, size / 2 - typeface.line_height * 0.56),
        initials,
        font=typeface.font,
        fill=readable_text(theme.accent),
    )
    return circle


def paste_avatar(
    image: Image.Image,
    avatar: Image.Image,
    origin: tuple[int, int],
    ring: RGB | None = None,
    *,
    ring_alpha: int = 235,
) -> None:
    """Paste a circular avatar, optionally with a ring around it."""
    x, y = origin
    size = avatar.size[0]

    if ring is not None:
        draw = ImageDraw.Draw(image, "RGBA")
        width = max(round(size * 0.025), 3)
        draw.ellipse(
            (x - width, y - width, x + size + width, y + size + width),
            outline=with_alpha(ring, ring_alpha),
            width=width,
        )

    image.paste(avatar, (x, y), avatar)


def avatar_stack(
    image: Image.Image,
    faces: Sequence[Image.Image],
    origin: tuple[int, int],
    size: int,
    theme: Theme,
    *,
    overflow: int = 0,
) -> int:
    """Overlapping row of member photos, ending in a "+3" disc.

    Returns the width drawn, so the caller can centre the row in its column.
    """
    step = round(size * 0.68)
    x, y = origin
    ring = max(round(size * 0.06), 2)

    for index, face in enumerate(faces):
        draw = ImageDraw.Draw(image, "RGBA")
        left = x + index * step
        draw.ellipse(
            (left - ring, y - ring, left + size + ring, y + size + ring),
            fill=with_alpha(theme.background_bottom, 255),
        )
        image.paste(face, (left, y), face)

    drawn = len(faces)
    if overflow > 0:
        draw = ImageDraw.Draw(image, "RGBA")
        left = x + drawn * step
        draw.ellipse(
            (left - ring, y - ring, left + size + ring, y + size + ring), fill=with_alpha(theme.background_bottom, 255)
        )
        draw.ellipse((left, y, left + size, y + size), fill=theme.panel_border)

        typeface = get_font(round(size * 0.34), "bold")
        label = f"+{overflow}"
        label_width = text_width(draw, label, typeface)
        draw.text(
            (left + size / 2 - label_width / 2, y + size / 2 - typeface.line_height * 0.54),
            label,
            font=typeface.font,
            fill=theme.text,
        )
        drawn += 1

    return (drawn - 1) * step + size if drawn else 0


def hero_cover(
    image: Image.Image,
    source: Image.Image,
    box: Box,
    theme: Theme,
    *,
    clip: Image.Image | None = None,
) -> None:
    """Cover art in the top corner of a card, dissolved into the background.

    The fade is towards the card's own gradient rather than a fresh one, so
    the photo has no visible edge on the two sides that meet the layout - the
    title can then sit over the bottom of it without a seam.
    """
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    if width <= 0 or height <= 0:
        return

    backdrop = image.crop(box)
    fitted = ImageOps.fit(source.convert("RGB"), (width, height), Image.Resampling.LANCZOS, centering=(0.5, 0.38))

    # Feather: opaque in the top right corner, gone by the left edge and the
    # bottom. Built from two one dimensional ramps added together rather than
    # a per pixel loop, which is the difference between 2 ms and 80 ms on a
    # poster sized band.
    column = Image.new("L", (1, height))
    column_pixels = column.load()
    assert column_pixels is not None
    for y in range(height):
        ratio = min(max((y / height - 0.30) / 0.70, 0.0), 1.0)
        column_pixels[0, y] = round(255 * (ratio**1.6) * 0.92)

    row = Image.new("L", (width, 1))
    row_pixels = row.load()
    assert row_pixels is not None
    for x in range(width):
        ratio = min(max((0.42 - x / width) / 0.42, 0.0), 1.0)
        row_pixels[x, 0] = round(255 * ratio * 0.85)

    mask = ImageChops.add(
        column.resize((width, height), Image.Resampling.BILINEAR),
        row.resize((width, height), Image.Resampling.BILINEAR),
    )

    blended = Image.composite(backdrop, fitted, mask)
    # `clip` is the card's own rounded corner mask, so a band across the top
    # cannot square off the corners of the card it sits in.
    image.paste(blended, (x0, y0), clip)


def cover_wash(image: Image.Image, source: Image.Image, height: int, *, floor: int = 96) -> None:
    """Full width hero image behind the whole top of a landscape card."""
    width = image.size[0]
    backdrop = image.crop((0, 0, width, height))
    fitted = ImageOps.fit(source.convert("RGB"), (width, height), Image.Resampling.LANCZOS, centering=(0.5, 0.4))
    image.paste(fitted, (0, 0))

    scrim = Image.new("L", (1, height))
    pixels = scrim.load()
    assert pixels is not None
    fade_end = height * 0.88
    for y in range(height):
        ratio = min(y / fade_end, 1.0)
        pixels[0, y] = round(floor + (255 - floor) * ratio**1.5)

    image.paste(backdrop, (0, 0), scrim.resize((width, height), Image.Resampling.BILINEAR))


def qr_panel(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    url: str,
    center_x: int,
    top: int,
    size: int,
    *,
    padding: int,
    radius: int,
) -> int:
    """White rounded plate with the QR code centred on it. Returns the y below.

    The plate is always white whatever the theme: a dark QR on a dark card is
    the one thing a phone camera will not read.
    """
    left = round(center_x - size / 2)
    panel(
        draw,
        (left - padding, top - padding, left + size + padding, top + size + padding),
        radius,
        (255, 255, 255, 255),
    )
    image.paste(qr_image(url, size, (12, 16, 22), (255, 255, 255)), (left, top))
    return top + size + padding


def status_dot(draw: ImageDraw.ImageDraw, center: tuple[float, float], radius: float, color: RGB) -> None:
    x, y = center
    draw.ellipse((x - radius * 1.9, y - radius * 1.9, x + radius * 1.9, y + radius * 1.9), fill=with_alpha(color, 60))
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=with_alpha(color, 255))


def divider(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], theme: Theme) -> None:
    x0, y0, x1, y1 = box
    draw.line((x0, y0, x1, y1), fill=with_alpha(mix(theme.background_top, theme.accent, 0.35), 190), width=2)


def qr_image(url: str, size: int, foreground: RGB, background: RGB) -> Image.Image:
    """Share link as a QR code, sized to an exact pixel box."""
    code = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=1)
    code.add_data(url)
    code.make(fit=True)

    rendered = code.make_image(fill_color=_hex(foreground), back_color=_hex(background))
    image: Image.Image = rendered.get_image().convert("RGB")
    return image.resize((size, size), Image.Resampling.NEAREST)


def _hex(color: RGB) -> str:
    return "#{:02x}{:02x}{:02x}".format(*color)
