"""Font resolution.

Pillow font objects are not safe to share between threads while drawing, so
every worker thread keeps its own cache. Sizes are the ones the card layouts
ask for, and there are only a handful of them per thread.
"""

import threading
from dataclasses import dataclass
from functools import cache
from logging import getLogger
from pathlib import Path
from typing import Literal

from PIL import ImageFont

from ..settings import settings

logger = getLogger(__name__)

Weight = Literal["regular", "bold"]
FontType = ImageFont.FreeTypeFont | ImageFont.ImageFont

# Drop Inter/Poppins/whatever the brand uses in here and it wins over the
# system fonts. Files are matched on name, e.g. "Inter-Bold.ttf".
BUNDLED_FONT_DIR = Path(__file__).resolve().parent.parent / "static" / "fonts"

SYSTEM_FONTS: dict[Weight, tuple[str, ...]] = {
    "regular": (
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ),
    "bold": (
        "C:/Windows/Fonts/seguibl.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ),
}

_local = threading.local()


@dataclass(frozen=True)
class Typeface:
    """A loaded font plus the nominal size, which Pillow's built in font does
    not expose. Layout code needs the size for line spacing."""

    font: FontType
    size: int

    @property
    def line_height(self) -> int:
        return round(self.size * 1.28)


@cache
def resolve_font_path(weight: Weight) -> Path | None:
    """First configured font, then bundled, then system. None means fall back
    to Pillow's built in face."""
    configured = settings.render_font_bold if weight == "bold" else settings.render_font_regular
    if configured is not None:
        path = Path(configured)
        if path.is_file():
            return path
        logger.warning("Configured %s font not found at %s", weight, path)

    if BUNDLED_FONT_DIR.is_dir():
        for candidate in sorted(BUNDLED_FONT_DIR.glob("*.tt[fc]")):
            if weight in candidate.stem.lower():
                return candidate

    for system_font in SYSTEM_FONTS[weight]:
        path = Path(system_font)
        if path.is_file():
            return path

    return None


def _load(size: int, weight: Weight) -> FontType:
    path = resolve_font_path(weight)
    if path is not None:
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            logger.warning("Could not load font %s, falling back to the default face", path)

    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1 has no sizeable default font.
        return ImageFont.load_default()


def get_font(size: int, weight: Weight = "regular") -> Typeface:
    cache: dict[tuple[int, Weight], Typeface] | None = getattr(_local, "fonts", None)
    if cache is None:
        cache = {}
        _local.fonts = cache

    key = (size, weight)
    typeface = cache.get(key)
    if typeface is None:
        typeface = Typeface(font=_load(size, weight), size=size)
        cache[key] = typeface
    return typeface
