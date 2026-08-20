"""Tests for font resolution and glyph safety.

The renderer draws text with whatever face is on the box, and that ranges from
a brand font down to Pillow's bundled fallback (113 glyphs: no en dash, no
accented latin). None of those may put a tofu box on a card, so the checks here
run against the worst face available rather than the best.
"""

import pytest
from PIL import ImageFont

from image_processing_service.render.fonts import Typeface, _notdef_signature, get_font
from image_processing_service.samples import sample_request
from image_processing_service.services.share_cards import render_now


@pytest.fixture
def fallback() -> Typeface:
    """Pillow's built in face, i.e. a slim image with no fonts installed."""
    font = ImageFont.load_default(size=40)
    return Typeface(font=font, size=40, notdef=_notdef_signature(font))


def test_the_fallback_face_is_missing_the_glyphs_we_substitute(fallback):
    # Guards the premise of every test below: if Pillow ever bundles a fuller
    # face these become vacuous rather than failing, so assert the gap exists.
    assert fallback.notdef is not None
    assert not fallback.draws("–")
    assert not fallback.draws("é")
    assert fallback.draws("-")
    assert fallback.draws("e")


def test_a_time_range_keeps_its_separator_on_a_face_without_an_en_dash(fallback):
    assert fallback.safe("7:30 PM – 9:00 PM") == "7:30 PM - 9:00 PM"


def test_accented_names_fall_back_to_their_base_letters(fallback):
    assert fallback.safe("Café Ñandú Über") == "Cafe Nandu Uber"


def test_undrawable_characters_are_dropped_without_leaving_gaps(fallback):
    assert fallback.safe("Run 🏃 Club 日本") == "Run Club"


def test_text_the_face_can_draw_is_returned_untouched(fallback):
    assert fallback.safe("Friday Night Futsal") == "Friday Night Futsal"


def test_sanitising_is_idempotent(fallback):
    once = fallback.safe("7:30 PM – 9:00 PM · Café 🏃")
    assert fallback.safe(once) == once


def test_a_face_that_draws_every_glyph_changes_nothing():
    # A typeface with no detectable tofu box must not start stripping accents.
    typeface = Typeface(font=ImageFont.load_default(size=40), size=40, notdef=None)
    assert typeface.safe("Café – 🏃") == "Café – 🏃"
    assert typeface.draws("🏃")


def test_typefaces_are_cached_per_size_and_weight():
    assert get_font(32, "bold") is get_font(32, "bold")
    assert get_font(32, "bold") is not get_font(32, "regular")


def test_no_card_sends_an_undrawable_character_to_pillow(monkeypatch):
    """End to end: render every card kind on the fallback face and assert that
    nothing reaching `ImageDraw.text` would come out as a tofu box.

    Checking the strings rather than the pixels is what makes this precise - a
    finished card is full of rectangles (the QR block, the stat panels) that a
    pixel scan cannot tell apart from a .notdef box.
    """
    from PIL import ImageDraw

    from image_processing_service.render import fonts

    monkeypatch.setattr(fonts, "SYSTEM_FONTS", {"regular": (), "bold": ()})
    monkeypatch.setattr(fonts, "_local", fonts.threading.local())
    monkeypatch.setattr(fonts.settings, "render_font_regular", None)
    monkeypatch.setattr(fonts.settings, "render_font_bold", None)
    fonts.resolve_font_path.cache_clear()

    drawn: list[tuple[str, object]] = []
    original = ImageDraw.ImageDraw.text

    def record(self, xy, text, *args, **kwargs):
        drawn.append((text, kwargs.get("font") or (args[0] if args else None)))
        return original(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", record)

    try:
        for kind in ("USER", "SQUAD", "EVENT"):
            request = sample_request(kind=kind, layout="POSTER")
            request.payload.title = "Café Saturday Social Run 🏃"
            if hasattr(request.payload, "host_name"):  # Events carry a host, users do not.
                request.payload.host_name = "Ñoel Übermann"
            request.payload.subtitle = "Ünicode · naïve — café"

            result = render_now(request)
            assert result.status == "COMPLETED", result.error
    finally:
        fonts.resolve_font_path.cache_clear()

    assert drawn, "the render drew no text at all"

    faces: dict[int, Typeface] = {}
    for text, font in drawn:
        if font is None:
            continue
        face = faces.get(id(font))
        if face is None:
            face = faces[id(font)] = Typeface(font=font, size=1, notdef=_notdef_signature(font))
        undrawable = {character for character in text if not face.draws(character)}
        assert not undrawable, f"{undrawable} would draw as tofu in {text!r}"


def test_the_time_range_survives_the_render_on_a_bare_face(monkeypatch):
    """The reported bug: the en dash between two times drew as a box."""
    from image_processing_service.render.cards import format_event_time

    font = ImageFont.load_default(size=40)
    fallback = Typeface(font=font, size=40, notdef=_notdef_signature(font))

    request = sample_request(kind="EVENT")
    assert request.payload.starts_at is not None

    formatted = format_event_time(request.payload.starts_at, request.payload.ends_at)
    assert "–" in formatted  # The layout still asks for proper typography...
    assert fallback.safe(formatted) == formatted.replace("–", "-")  # ...and degrades to a hyphen.
