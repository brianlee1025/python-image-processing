"""Tests for the card design itself: the fallback cover, the icon set and the
pieces of the layout that a payload can switch on and off.

Pixels are compared rather than described - a layout test that only asserts
"it rendered" passes on a blank image.
"""

import base64
from io import BytesIO

import pytest
from PIL import Image

from image_processing_service.render.cards import (
    METRICS_BY_LAYOUT,
    _display_url,
    _split_venue,
    _user_stats,
    format_event_day,
    format_event_time,
    format_post_date,
    render_card,
)
from image_processing_service.render.covers import default_cover
from image_processing_service.render.icons import ICON_NAMES, sport_icon, stat_icon
from image_processing_service.render.palette import (
    TIER_COLORS,
    contrast_ratio,
    readable_text,
    resolve_theme,
    tier_for_level,
)
from image_processing_service.samples import sample_request
from image_processing_service.schemas.cards import RenderRequest, UserCard
from image_processing_service.settings import settings


def photo(size=(600, 400), color=(120, 90, 60)) -> str:
    image = Image.new("RGB", size, color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def request_for(kind: str, **payload) -> RenderRequest:
    return RenderRequest.model_validate({"kind": kind, "payload": {"title": "Ballers", **payload}})


def band_colors(image: Image.Image) -> set[tuple[int, int, int]]:
    """Distinct colours across the middle of the cover band."""
    metrics = METRICS_BY_LAYOUT["POSTER"]
    y = metrics.frame + round(image.height * 0.12)
    return {image.getpixel((x, y)) for x in range(metrics.frame + 40, image.width - metrics.frame - 40, 12)}


def variety(image: Image.Image, box: tuple[int, int, int, int]) -> int:
    """How many distinct colours a region holds. `getcolors` rather than
    `getdata` because the latter is deprecated in Pillow 12."""
    return len(image.crop(box).getcolors(maxcolors=1_000_000) or [])


def _has_color(image: Image.Image, color: tuple[int, int, int], tolerance: int = 6) -> bool:
    """Whether a colour is actually painted, allowing for antialiased edges."""
    return any(
        all(abs(channel - target) <= tolerance for channel, target in zip(painted, color))
        for _, painted in (image.getcolors(maxcolors=1_000_000) or [])
    )


def white_pixels(image: Image.Image) -> int:
    return sum(count for count, color in (image.getcolors(maxcolors=1_000_000) or []) if color == (255, 255, 255))


@pytest.mark.parametrize("kind", ["SQUAD", "EVENT"])
def test_a_card_without_a_banner_gets_generated_cover_art(kind):
    """The common case: nobody uploaded anything."""
    plain = render_card(request_for(kind))

    assert len(band_colors(plain)) > 4


def test_a_player_card_has_no_cover_band():
    """A namecard is a face, not a poster - the band would push the identity
    block off its own card."""
    metrics = METRICS_BY_LAYOUT["POSTER"]
    strip = (metrics.frame + 40, metrics.frame + 4, 1080 - metrics.frame - 40, metrics.frame + 40)

    player = variety(render_card(request_for("USER", title="Aisyah Rahman")), strip)
    squad = variety(render_card(request_for("SQUAD")), strip)

    assert player * 3 < squad


def test_a_supplied_banner_wins_over_the_generated_one():
    generated = render_card(request_for("SQUAD"))
    supplied = render_card(request_for("SQUAD", coverBase64=photo((1200, 700), (200, 40, 40))))

    assert band_colors(generated) != band_colors(supplied)


def test_a_post_without_a_photo_gets_no_generated_band():
    """Most posts are just words. A squad or event without art gets a stand
    in band; a text only post should not - there is nothing to stand in for."""
    metrics = METRICS_BY_LAYOUT["POSTER"]
    strip = (metrics.frame + 40, metrics.frame + 4, 1080 - metrics.frame - 40, metrics.frame + 40)

    post = variety(render_card(request_for("POST", title="Aisyah Rahman", description="Great session today.")), strip)
    squad = variety(render_card(request_for("SQUAD")), strip)

    assert post * 3 < squad


def test_a_posts_supplied_photo_still_renders_as_a_band():
    plain = render_card(request_for("POST", title="Aisyah Rahman", description="Great session today."))
    with_photo = render_card(
        request_for("POST", title="Aisyah Rahman", description="Great session today.", coverBase64=photo())
    )

    assert band_colors(plain) != band_colors(with_photo)


def test_bundled_cover_files_are_preferred_over_generated_art(tmp_path, monkeypatch):
    flat = Image.new("RGB", (600, 300), (7, 9, 11))
    flat.save(tmp_path / "squad.png")
    monkeypatch.setattr(settings, "render_default_cover_dir", tmp_path)

    cover = default_cover("SQUAD", "Football", (600, 300), resolve_theme(None, "SQUAD"))

    assert cover.getpixel((10, 10)) == (7, 9, 11)


def test_an_unreadable_cover_file_does_not_fail_the_card(tmp_path, monkeypatch):
    (tmp_path / "squad.png").write_bytes(b"not an image")
    monkeypatch.setattr(settings, "render_default_cover_dir", tmp_path)

    assert default_cover("SQUAD", None, (400, 200), resolve_theme(None, "SQUAD")).size == (400, 200)


def test_generated_covers_are_cached_per_theme_and_sport():
    theme = resolve_theme(None, "SQUAD")
    first = default_cover("SQUAD", "Football", (400, 200), theme)
    second = default_cover("SQUAD", "Football", (400, 200), theme)
    other = default_cover("SQUAD", "Swimming", (400, 200), theme)

    assert first.tobytes() == second.tobytes()
    assert first.tobytes() != other.tobytes()
    # Copies, so one card cannot draw on the next card's cover.
    assert first is not second


@pytest.mark.parametrize("kind", ["USER", "SQUAD", "EVENT", "POST"])
def test_the_qr_code_is_drawn_on_white_whatever_the_theme(kind):
    """A dark QR on a dark card is the one thing a phone will not read."""
    assert white_pixels(render_card(sample_request(kind=kind))) > 20_000


def test_a_card_without_a_share_url_draws_no_qr_plate():
    assert white_pixels(render_card(request_for("SQUAD", subtitle="No link here"))) < 5_000


def test_the_card_sits_on_a_page_so_its_corners_read_as_a_card():
    image = render_card(sample_request(kind="SQUAD"))
    corner = image.getpixel((2, 2))
    middle = image.getpixel((image.width // 2, image.height // 2))

    assert sum(corner) < sum(middle)


def test_member_avatars_render_as_a_stack():
    without = render_card(request_for("SQUAD", memberCount=9, stats=[{"label": "Members", "value": "9"}]))
    with_faces = render_card(
        request_for(
            "SQUAD",
            memberCount=9,
            stats=[{"label": "Members", "value": "9"}],
            memberAvatarsBase64=[photo((200, 200), (220, 40, 40)), photo((200, 200), (40, 220, 40))],
        )
    )

    assert without.tobytes() != with_faces.tobytes()


def test_unusable_member_avatars_are_dropped_not_fatal():
    image = render_card(request_for("SQUAD", memberCount=4, memberAvatarsBase64=["nonsense", photo((80, 80))]))

    assert image.size == (1080, 1350)


def test_the_call_to_action_and_actions_can_be_overridden():
    default = render_card(request_for("SQUAD", shareUrl="https://playbookapp.org/s/abc"))
    custom = render_card(
        request_for(
            "SQUAD",
            shareUrl="https://playbookapp.org/s/abc",
            ctaLabel="Scan to see the fixtures",
            actions=["Copy link"],
        )
    )

    assert default.tobytes() != custom.tobytes()


@pytest.mark.parametrize("kind", ["USER", "SQUAD", "EVENT", "POST"])
def test_no_affordance_row_unless_the_payload_asks_for_one(kind):
    """On a flat image, "Add to calendar" is a caption for a control that is not
    there. The card ends on its link unless a caller says otherwise.

    Compared against an explicitly empty list rather than eyeballing a band:
    identical pixels is exactly the claim that nothing was invented.
    """
    link = "https://playbookapp.org/s/abc"
    default = render_card(request_for(kind, shareUrl=link))
    explicitly_none = render_card(request_for(kind, shareUrl=link, actions=[]))
    asked = render_card(request_for(kind, shareUrl=link, actions=["Add to calendar"]))

    assert default.tobytes() == explicitly_none.tobytes()
    assert default.tobytes() != asked.tobytes()


def test_a_verified_player_gets_a_tick():
    plain = render_card(request_for("USER", title="Admin Lee", handle="@adminnn"))
    verified = render_card(request_for("USER", title="Admin Lee", handle="@adminnn", verified=True))

    assert plain.tobytes() != verified.tobytes()


def test_a_verified_poster_gets_a_tick():
    plain = render_card(request_for("POST", title="Admin Lee", handle="@adminnn", description="Hello!"))
    verified = render_card(
        request_for("POST", title="Admin Lee", handle="@adminnn", description="Hello!", verified=True)
    )

    assert plain.tobytes() != verified.tobytes()


def test_a_posts_like_and_comment_counts_render():
    without = render_card(request_for("POST", title="Admin Lee", description="Hello!"))
    with_stats = render_card(
        request_for(
            "POST",
            title="Admin Lee",
            description="Hello!",
            stats=[{"label": "Likes", "value": "56"}, {"label": "Comments", "value": "3"}],
        )
    )

    assert without.tobytes() != with_stats.tobytes()


def test_a_post_with_only_a_photo_and_no_caption_still_renders():
    """A post can be a photo with nothing typed. The renderer should not
    assume `description` is there just because every other field might be."""
    image = render_card(request_for("POST", title="Admin Lee", coverBase64=photo()))
    assert image.size == (1080, 1350)


def test_a_content_image_replaces_the_drawn_body():
    """A screenshot of the post reproduces things this renderer cannot -
    highlighted dates, emoji, a photo grid - so it wins over drawing the
    title/description/stats from scratch when both are sent."""
    drawn = render_card(
        request_for(
            "POST",
            title="Admin Lee",
            handle="@adminnn",
            description="Great session today!",
            stats=[{"label": "Likes", "value": "12"}],
        )
    )
    screenshot = render_card(
        request_for(
            "POST",
            title="Admin Lee",
            handle="@adminnn",
            description="Great session today!",
            stats=[{"label": "Likes", "value": "12"}],
            contentImageBase64=photo((900, 500), (250, 250, 255)),
        )
    )

    assert drawn.tobytes() != screenshot.tobytes()


@pytest.mark.parametrize("shape", [(900, 400), (400, 1200), (300, 300)])
def test_a_content_image_of_any_shape_stays_inside_the_card(shape):
    """Letterboxed, not cropped or stretched: a caption cut in half or a
    squashed photo would misrepresent the post."""
    metrics = METRICS_BY_LAYOUT["POSTER"]
    image = render_card(request_for("POST", title="Admin Lee", contentImageBase64=photo(shape, (250, 250, 255))))

    for x in (metrics.frame + 4, image.width - metrics.frame - 4):
        for y in (metrics.frame + 4, image.height - metrics.frame - 4):
            assert image.getpixel((x, y)) != (250, 250, 255)


def test_an_unusable_content_image_still_renders_a_card():
    image = render_card(request_for("POST", title="Admin Lee", contentImageBase64="not-an-image"))
    assert image.size == (1080, 1350)


def test_the_level_badge_is_coloured_by_tier():
    """A card and a profile should read as the same person at the same rank."""
    common = render_card(request_for("USER", title="Admin Lee", handle="@adminnn", level=1))
    legendary = render_card(request_for("USER", title="Admin Lee", handle="@adminnn", level=18))

    assert common.tobytes() != legendary.tobytes()
    # The tier colour reaches the card - the pill and the avatar ring both use it.
    assert _has_color(legendary, TIER_COLORS["legendary"])
    assert not _has_color(legendary, TIER_COLORS["common"])


def test_a_player_without_a_level_still_renders():
    assert render_card(request_for("USER", title="Admin Lee", handle="@adminnn")).size == (1080, 1350)


def test_the_tier_ladder_matches_the_frontend():
    """Mirrors TIER_MIN_LEVEL in playbook-web's tier.constant.ts. If these drift,
    a player is one colour in the app and another on their card."""
    assert [tier_for_level(level) for level in (1, 2)] == ["common", "common"]
    assert [tier_for_level(level) for level in (3, 5)] == ["rare", "rare"]
    assert [tier_for_level(level) for level in (6, 9)] == ["epic", "epic"]
    assert [tier_for_level(level) for level in (10, 14)] == ["unique", "unique"]
    assert [tier_for_level(level) for level in (15, 99)] == ["legendary", "legendary"]
    assert tier_for_level(None) == "common"
    assert tier_for_level(0) == "common"


def test_the_level_is_not_printed_twice():
    """playbook-be leads its user stats with Level, which is now a badge."""
    card = request_for(
        "USER",
        title="Admin Lee",
        level=7,
        stats=[
            {"label": "Level", "value": "7"},
            {"label": "XP", "value": "4.5k"},
            {"label": "Squads", "value": "6"},
        ],
    ).payload
    assert isinstance(card, UserCard)

    assert [stat.label for stat in _user_stats(card)] == ["XP", "Squads"]

    # Without a level there is no badge, so the stat is the only place it shows.
    unranked = request_for("USER", title="Admin Lee", stats=[{"label": "Level", "value": "7"}]).payload
    assert isinstance(unranked, UserCard)
    assert [stat.label for stat in _user_stats(unranked)] == ["Level"]


def test_a_long_venue_is_clipped_instead_of_running_off_the_card():
    """A full postal address is wider than half a card, and the panel it sits in
    is the only thing that knows how much room there is."""
    metrics = METRICS_BY_LAYOUT["POSTER"]
    base = {
        "startsAt": "2026-08-20T19:30:00+08:00",
        "stats": [{"label": "Going", "value": "1"}],
        "shareUrl": "https://playbookapp.org/e/abc",
    }
    short = render_card(request_for("EVENT", venue="KLCC Park", **base))
    long = render_card(
        request_for(
            "EVENT",
            venue="KLCC Park, Kampung Cendana, Kuala Lumpur, 50088, Wilayah Persekutuan, Malaysia",
            **base,
        )
    )

    # Whatever the address, nothing is drawn in the margin beside the panel.
    margin_band = (1080 - metrics.margin + 6, 0, 1080 - metrics.frame, 1350)
    assert short.crop(margin_band).tobytes() == long.crop(margin_band).tobytes()


@pytest.mark.parametrize("layout", ["POSTER", "STORY", "CARD"])
def test_every_layout_draws_every_kind(layout):
    for kind in ("USER", "SQUAD", "EVENT", "POST"):
        image = render_card(sample_request(kind=kind, layout=layout))
        assert variety(image, (0, 0, image.width, image.height)) > 100


def test_long_text_does_not_escape_the_card():
    """Everything is drawn inside the frame, so the page margin stays clean."""
    image = render_card(
        request_for(
            "USER",
            title="Muhammad Zulhilmi Bin Abdul Rahman Al-Hafiz",
            description="Bio. " * 300,
            handle="@" + "z" * 60,
            location="Kampung Baru, " * 6,
        )
    )
    theme = resolve_theme(None, "USER")
    page = tuple(round(channel * 0.28) for channel in theme.background_bottom)

    for x in (1, image.width - 2):
        for y in (1, image.height - 2):
            assert sum(image.getpixel((x, y))) <= sum(page) + 12


def test_icons_cover_the_sports_and_stat_labels_the_backend_sends():
    for sport in ("Football", "Futsal", "Badminton", "Running", "Cycling", "Swimming", "Yoga", "Basketball"):
        assert sport_icon(sport) in ICON_NAMES

    for label in (
        "Members",
        "Going",
        "Spots",
        "Duration",
        "Price",
        "Level",
        "Squads",
        "Founded",
        "Captain",
        "Likes",
        "Comments",
        "Shares",
    ):
        assert stat_icon(label) in ICON_NAMES


def test_an_unknown_sport_still_gets_a_pictogram():
    assert sport_icon("Underwater hockey") == "ball"
    assert stat_icon("Vibes") is None


def test_chip_text_keeps_its_contrast_on_every_accent():
    for kind in ("USER", "SQUAD", "EVENT", "POST"):
        accent = resolve_theme(None, kind).accent
        assert contrast_ratio(readable_text(accent), accent) >= 3.0


def test_share_links_are_printed_without_the_scheme():
    assert _display_url("https://playbookapp.org/s/zb9l8qk") == "playbookapp.org/s/zb9l8qk"
    assert _display_url("https://www.playbookapp.org/e/abc/") == "playbookapp.org/e/abc"
    assert _display_url(None) is None


def test_a_venue_breaks_at_its_first_comma():
    assert _split_venue("KLCQ Park, Kampung Cenderas, Kuala Lumpur") == "KLCQ Park\nKampung Cenderas, Kuala Lumpur"
    assert _split_venue("KLCC Park") == "KLCC Park"


def test_event_times_are_drawn_in_the_offset_they_arrive_in():
    request = RenderRequest.model_validate(
        {
            "kind": "EVENT",
            "payload": {
                "title": "Futsal",
                "startsAt": "2026-08-20T19:30:00+08:00",
                "endsAt": "2026-08-20T21:00:00+08:00",
            },
        }
    )
    starts = request.payload.starts_at
    assert starts is not None

    assert format_event_day(starts) == "Thu, 20 Aug 2026"
    assert format_event_time(starts, request.payload.ends_at) == "7:30 PM – 9:00 PM"


def test_post_dates_are_printed_as_an_absolute_time_not_a_relative_one():
    """A share card is a static image; "2h ago" would go stale the moment
    someone looks at it the next day."""
    request = RenderRequest.model_validate(
        {"kind": "POST", "payload": {"title": "Aisyah", "postedAt": "2026-08-20T19:05:00+08:00"}}
    )
    posted_at = request.payload.posted_at
    assert posted_at is not None

    assert format_post_date(posted_at) == "20 Aug · 7:05 PM"
