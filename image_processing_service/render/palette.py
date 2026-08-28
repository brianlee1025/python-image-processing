"""Colour themes for the share cards.

One theme per card kind, all built the same way: a near black background with
the kind's hue mixed in, one saturated accent that carries the identity, and
everything else - borders, panels, chips - derived from those two so a new
theme is six colours rather than twenty.
"""

from dataclasses import dataclass, replace

RGB = tuple[int, int, int]
RGBA = tuple[int, int, int, int]


@dataclass(frozen=True)
class Theme:
    name: str
    background_top: RGB
    background_bottom: RGB
    accent: RGB
    surface: RGB
    text: RGB
    muted: RGB

    @property
    def border(self) -> RGB:
        """The card outline: the accent pulled most of the way back into the
        background so it reads as an edge, not as a highlight."""
        return mix(self.background_bottom, self.accent, 0.42)

    @property
    def panel(self) -> RGBA:
        """Fill for the stat and detail panels."""
        return with_alpha(mix(self.background_top, self.accent, 0.10), 210)

    @property
    def panel_border(self) -> RGBA:
        return with_alpha(mix(self.background_top, self.accent, 0.30), 235)

    @property
    def chip_fill(self) -> RGBA:
        return with_alpha(mix(self.background_top, self.accent, 0.22), 235)

    @property
    def on_accent(self) -> RGB:
        return readable_text(self.accent)


THEMES: dict[str, Theme] = {
    # Player cards. Blue, the calmest of the three, because a namecard is the
    # one people put on a profile rather than a poster.
    "midnight": Theme(
        name="midnight",
        background_top=(12, 24, 54),
        background_bottom=(6, 12, 30),
        accent=(59, 130, 246),
        surface=(255, 255, 255),
        text=(238, 244, 255),
        muted=(150, 172, 208),
    ),
    # Squad cards.
    "turf": Theme(
        name="turf",
        background_top=(8, 34, 24),
        background_bottom=(4, 16, 12),
        accent=(45, 212, 126),
        surface=(255, 255, 255),
        text=(236, 253, 245),
        muted=(140, 178, 158),
    ),
    # Event cards.
    "sunset": Theme(
        name="sunset",
        background_top=(46, 16, 12),
        background_bottom=(20, 8, 8),
        accent=(249, 115, 22),
        surface=(255, 255, 255),
        text=(255, 242, 234),
        muted=(198, 156, 138),
    ),
    "court": Theme(
        name="court",
        background_top=(44, 30, 6),
        background_bottom=(18, 12, 4),
        accent=(250, 188, 45),
        surface=(255, 255, 255),
        text=(255, 249, 235),
        muted=(196, 176, 130),
    ),
    "ocean": Theme(
        name="ocean",
        background_top=(6, 38, 54),
        background_bottom=(3, 16, 24),
        accent=(45, 199, 224),
        surface=(255, 255, 255),
        text=(233, 250, 255),
        muted=(140, 180, 196),
    ),
    # Post cards. Violet, distinct from the other three hues so a shared post
    # never reads as a mis-tagged squad or event card.
    "dusk": Theme(
        name="dusk",
        background_top=(30, 16, 54),
        background_bottom=(14, 8, 26),
        accent=(167, 139, 250),
        surface=(255, 255, 255),
        text=(245, 240, 255),
        muted=(176, 162, 208),
    ),
}

DEFAULT_THEME_BY_KIND: dict[str, str] = {
    "USER": "midnight",
    "SQUAD": "turf",
    "EVENT": "sunset",
    "POST": "dusk",
}


# Level tiers, mirroring `tier.constant.ts` in playbook-web and the
# `--pb-tier-*` tokens in its dark theme. A card is a dark surface, so the dark
# values are the right ones: the light palette goes muddy on #102528.
#
# Levels 1-2 stay common on purpose - handing out a colour for signing up makes
# the whole ladder mean nothing.
TIER_MIN_LEVEL: tuple[tuple[str, int], ...] = (
    ("legendary", 15),
    ("unique", 10),
    ("epic", 6),
    ("rare", 3),
    ("common", 1),
)

TIER_COLORS: dict[str, RGB] = {
    "common": (169, 188, 191),
    "rare": (255, 154, 99),
    "epic": (255, 109, 143),
    "unique": (245, 200, 74),
    "legendary": (99, 199, 232),
}


def tier_for_level(level: int | None) -> str:
    """The tier a level sits in. Unknown levels read as common."""
    safe = max(1, int(level or 1))
    for tier, minimum in TIER_MIN_LEVEL:
        if safe >= minimum:
            return tier
    return "common"


def tier_color(level: int | None) -> RGB:
    return TIER_COLORS[tier_for_level(level)]


def parse_hex_color(value: str | None) -> RGB | None:
    """Accepts "#RRGGBB" / "RRGGBB" / "#RGB". Returns None for anything else,
    so a bad colour from the backend degrades to the theme accent."""
    if not value:
        return None

    text = value.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(char * 2 for char in text)
    if len(text) != 6:
        return None

    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return None


def resolve_theme(name: str | None, kind: str, accent_override: str | None = None) -> Theme:
    key = (name or DEFAULT_THEME_BY_KIND.get(kind, "midnight")).strip().lower()
    theme = THEMES.get(key, THEMES[DEFAULT_THEME_BY_KIND.get(kind, "midnight")])

    accent = parse_hex_color(accent_override)
    if accent is not None:
        # A squad's own colour replaces the accent but not the backdrop: the
        # card stays legible whatever hex the backend sends.
        theme = replace(theme, accent=accent)
    return theme


def with_alpha(color: RGB, alpha: int) -> RGBA:
    return (color[0], color[1], color[2], alpha)


def mix(first: RGB, second: RGB, amount: float) -> RGB:
    """Linear blend, `amount` 0.0 keeps `first` and 1.0 keeps `second`."""
    ratio = min(max(amount, 0.0), 1.0)
    return (
        round(first[0] + (second[0] - first[0]) * ratio),
        round(first[1] + (second[1] - first[1]) * ratio),
        round(first[2] + (second[2] - first[2]) * ratio),
    )


def lighten(color: RGB, amount: float) -> RGB:
    return mix(color, (255, 255, 255), amount)


def darken(color: RGB, amount: float) -> RGB:
    return mix(color, (0, 0, 0), amount)


def relative_luminance(color: RGB) -> float:
    """WCAG relative luminance, used to pick text colour by contrast."""

    def channel(value: int) -> float:
        ratio = value / 255
        return ratio / 12.92 if ratio <= 0.03928 else ((ratio + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(color[0]) + 0.7152 * channel(color[1]) + 0.0722 * channel(color[2])


def contrast_ratio(first: RGB, second: RGB) -> float:
    lighter, darker = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def readable_text(background: RGB) -> RGB:
    """Ink or white for text sitting on `background`.

    Card labels are bold and large, so white is kept while it clears WCAG's
    3:1 large text ratio and dropped to ink below that. A plain brightness
    threshold would leave white on the green squad accent at 2:1.
    """
    white = (255, 255, 255)
    return white if contrast_ratio(white, background) >= 3.0 else (17, 20, 28)
