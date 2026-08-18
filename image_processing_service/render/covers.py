"""Fallback cover art.

Most squads never upload a banner, and an event usually inherits whatever the
squad has, which is nothing. A card with an empty top edge looks broken rather
than minimal, so a stand in is generated from the theme and the sport: a
tinted wash, a few angled bands and an oversized sport pictogram.

A deployment that would rather ship real photography drops files into
`image_processing_service/static/covers` (or points `RENDER_DEFAULT_COVER_DIR`
somewhere) and they win over the generated art. Lookup is most specific first:

    squad-football.jpg  ->  event-futsal.png  ->  football.jpg  ->  squad.jpg  ->  cover.jpg
"""

from functools import lru_cache
from logging import getLogger
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from ..settings import settings
from .icons import draw_icon, sport_icon
from .palette import RGB, Theme, darken, mix, with_alpha

logger = getLogger(__name__)

BUNDLED_COVER_DIR = Path(__file__).resolve().parent.parent / "static" / "covers"

SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")


def default_cover(kind: str, sport: str | None, size: tuple[int, int], theme: Theme) -> Image.Image:
    """Cover art for a card whose payload carried none."""
    supplied = _bundled_cover(kind, sport)
    if supplied is not None:
        return supplied

    return _generated_cover(kind, sport_icon(sport), size, theme.name, theme.accent, theme.background_top).copy()


def _bundled_cover(kind: str, sport: str | None) -> Image.Image | None:
    directories = [directory for directory in (settings.render_default_cover_dir, BUNDLED_COVER_DIR) if directory]
    slug = _slug(sport)
    kind_slug = kind.lower()

    names = [f"{kind_slug}-{slug}", kind_slug, slug, "cover"] if slug else [kind_slug, "cover"]

    for directory in directories:
        for name in names:
            for suffix in SUFFIXES:
                path = Path(directory) / f"{name}{suffix}"
                if path.is_file():
                    try:
                        return Image.open(path).convert("RGB")
                    except OSError as error:
                        # A broken file on disk is an operator problem, not a
                        # reason to fail somebody's share card.
                        logger.warning("Unusable default cover %s: %s", path, error)
    return None


def _slug(value: str | None) -> str:
    if not value:
        return ""
    return "".join(character if character.isalnum() else "-" for character in value.strip().lower()).strip("-")


@lru_cache(maxsize=32)
def _generated_cover(
    kind: str,
    icon: str,
    size: tuple[int, int],
    theme_name: str,
    accent: RGB,
    background: RGB,
) -> Image.Image:
    """Deterministic per (kind, sport, size, theme), so it is worth caching:
    every squad without a banner in a given theme shares one image."""
    width, height = size
    image = Image.new("RGB", size, darken(background, 0.25))
    draw = ImageDraw.Draw(image, "RGBA")

    # Diagonal bands, brightest towards the top right where the card's own
    # glow sits.
    band = max(round(width * 0.085), 8)
    for index in range(-height // band, (width + height) // band + 1):
        x = index * band * 2
        shade = mix(background, accent, 0.09 + 0.07 * (index % 3))
        draw.polygon(
            [(x, height), (x + band, height), (x + band + height, 0), (x + height, 0)],
            fill=with_alpha(shade, 210),
        )

    glow = Image.new("L", (max(width // 4, 1), max(height // 4, 1)), 0)
    radius = max(width // 8, 4)
    ImageDraw.Draw(glow).ellipse(
        (width // 4 - radius, -radius, width // 4 + radius * 3, radius * 2),
        fill=90,
    )
    glow = glow.filter(ImageFilter.GaussianBlur(radius / 2))
    image.paste(Image.new("RGB", size, accent), (0, 0), glow.resize(size, Image.Resampling.BILINEAR))

    # The sport itself, oversized and mostly submerged: recognisable at a
    # glance, never competing with the title that lands on top of it.
    mark = round(min(width, height) * 0.86)
    draw_icon(
        draw,
        icon,
        (width * 0.62, height * 0.10, width * 0.62 + mark, height * 0.10 + mark),
        with_alpha(mix(accent, (255, 255, 255), 0.45), 38),
        width=max(round(mark * 0.035), 3),
    )

    return image
