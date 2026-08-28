"""Font resolution.

Pillow font objects are not safe to share between threads while drawing, so
every worker thread keeps its own cache. Sizes are the ones the card layouts
ask for, and there are only a handful of them per thread.

The faces underneath vary a lot - a brand font when one is configured, DejaVu
on a Linux box, and Pillow's built in fallback (113 glyphs, no accents, no en
dash) when an image ships without fonts installed. Card text mixes our own
typography with whatever a user typed into a squad name, so `Typeface.safe`
exists to guarantee the one outcome nobody wants: a row of tofu boxes.
"""

import threading
import unicodedata
from dataclasses import dataclass, field
from functools import cache
from logging import getLogger
from pathlib import Path
from typing import Literal

from PIL import ImageFont

from ..settings import settings

logger = getLogger(__name__)

Weight = Literal["regular", "bold"]
FontType = ImageFont.FreeTypeFont | ImageFont.ImageFont

# A rendered glyph, as (size, bitmap). Two characters that share one are the
# same drawing, which is how a missing glyph is spotted: it is the .notdef box.
Signature = tuple[tuple[int, int], bytes]

# Punctuation the layouts use that a fallback face may not carry, and what to
# draw instead. Substituting beats dropping: a time range still reads as a
# range with a hyphen, where "4:00 PM 5:30 PM" does not.
SUBSTITUTIONS: dict[str, str] = {
    "\u2010": "-",  # hyphen
    "\u2011": "-",  # non breaking hyphen
    "\u2012": "-",  # figure dash
    "\u2013": "-",  # en dash, the one in every time range
    "\u2014": "-",  # em dash
    "\u2015": "-",  # horizontal bar
    "\u2018": "'",
    "\u2019": "'",
    "\u201a": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u201e": '"',
    "\u2022": "-",  # bullet
    "\u2026": "...",
    "\u00b7": "-",  # middle dot
    "\u00d7": "x",
    "\u2192": "->",
    "\u00a0": " ",
    "\u202f": " ",  # narrow no break space, arrives in some locale time formats
    "\u2009": " ",
}

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


def _signature(font: FontType, text: str) -> Signature | None:
    """What `font` actually draws for `text`, or None if it cannot be asked."""
    try:
        mask = font.getmask(text, mode="1")
    except Exception:  # noqa: BLE001 - a face that will not measure is a face we do not police.
        return None
    return mask.size, bytes(mask)


def _notdef_signature(font: FontType) -> Signature | None:
    """The box this face draws in place of a glyph it does not have.

    None when there is nothing to detect: either the face will not report, or
    it draws missing glyphs as blanks, in which case comparing against it would
    flag every space in the card.
    """
    notdef = _signature(font, "\ue000")  # Private use, mapped by essentially nothing.
    if notdef is None or not any(notdef[1]):
        return None
    if notdef == _signature(font, " "):
        return None
    return notdef


@dataclass(frozen=True)
class Typeface:
    """A loaded font plus the nominal size, which Pillow's built in font does
    not expose. Layout code needs the size for line spacing."""

    font: FontType
    size: int
    # The tofu box for this face, and a lazily filled per character record of
    # what it can draw. One Typeface exists per size per thread, so the cache
    # lives exactly as long as the font it describes.
    notdef: Signature | None = field(default=None, compare=False, repr=False)
    _drawable: dict[str, bool] = field(default_factory=dict, compare=False, repr=False)

    @property
    def line_height(self) -> int:
        return round(self.size * 1.28)

    def draws(self, character: str) -> bool:
        """Whether this face has a real glyph for `character`."""
        if self.notdef is None:
            return True

        cached = self._drawable.get(character)
        if cached is None:
            cached = _signature(self.font, character) != self.notdef
            self._drawable[character] = cached
        return cached

    def safe(self, text: str) -> str:
        """`text` with everything this face cannot draw replaced or removed.

        Known punctuation is substituted, accented letters fall back to their
        base letter, and anything still undrawable - CJK, emoji in a squad name
        - is dropped rather than rendered as a box.
        """
        if self.notdef is None or all(self.draws(character) for character in text):
            return text

        out: list[str] = []
        dropped = False
        for character in text:
            if self.draws(character):
                out.append(character)
                continue

            replacement = SUBSTITUTIONS.get(character)
            if replacement is None:
                stripped = unicodedata.normalize("NFKD", character)
                replacement = "".join(part for part in stripped if not unicodedata.combining(part))

            kept = "".join(part for part in replacement if self.draws(part))
            dropped = dropped or not kept
            out.append(kept)

        # Dropping a character mid word leaves the gap it sat in behind.
        return " ".join("".join(out).split()) if dropped else "".join(out)


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
        font = _load(size, weight)
        typeface = Typeface(font=font, size=size, notdef=_notdef_signature(font))
        cache[key] = typeface
    return typeface
