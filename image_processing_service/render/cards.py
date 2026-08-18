"""Card composition: turns a `RenderRequest` into a finished Pillow image.

Each kind gets its own layout, because they are answering different questions.
A squad card sells a group ("who are these people, can I join"), a player card
is a namecard ("this is me, here is my handle"), an event poster is a listing
("what, when, where, how much"). One generic template drawn three times made
all three read like a form.

What they share is the frame. Every card is a rounded panel on a darker page
with an accent outline, a brand row at the top, and a bottom block - call to
action, QR code, link, affordances - anchored to the floor. Layout is two
pass: the bottom block is measured and placed first, the detail panel is
hung above it, and the hero content flows into whatever is left. That keeps a
squad with a three word tagline and one with a 300 word bio on the same grid.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from logging import getLogger

from PIL import Image, ImageChops, ImageDraw

from ..schemas.cards import BaseCard, EventCard, RenderRequest, SquadCard, Stat, UserCard
from ..settings import settings
from .canvas import (
    PAGE_TINT,
    avatar_stack,
    card_border,
    chip,
    circle_image,
    cover_wash,
    divider,
    draw_lines,
    ellipsize,
    fit_text,
    hero_cover,
    icon_row,
    icon_row_width,
    initials_avatar,
    new_canvas,
    panel,
    paste_avatar,
    qr_panel,
    rounded_mask,
    status_dot,
    text_width,
    tracked_text,
    tracked_width,
)
from .covers import default_cover
from .fonts import Typeface, get_font
from .icons import badge, draw_icon, sport_icon, stat_icon
from .media import SourceImageError, load_source
from .palette import Theme, darken, readable_text, resolve_theme, tier_color, with_alpha

logger = getLogger(__name__)

KIND_LABELS = {"USER": "PLAYER CARD", "SQUAD": "SQUAD", "EVENT": "EVENT"}

CTA_LABELS = {
    "USER": "SCAN TO VIEW PROFILE",
    "SQUAD": "SCAN TO JOIN THE SQUAD",
    "EVENT": "SCAN TO JOIN THE EVENT",
}

# Icons for the optional affordance row under the link. Matched on a keyword so
# a translated or reworded action still finds something; unknown wording simply
# gets no icon.
ACTION_ICONS: tuple[tuple[str, str], ...] = (
    ("calendar", "calendar"),
    ("invite", "user-plus"),
    ("connect", "user-plus"),
    ("add", "user-plus"),
    ("follow", "star"),
    ("share", "share"),
    ("copy", "link"),
    ("link", "link"),
)

# Cards without a banner get generated art instead of an empty top edge.
COVER_KINDS = {"SQUAD", "EVENT"}


@dataclass(frozen=True)
class Metrics:
    margin: int
    frame: int
    card_radius: int
    panel_radius: int
    title_sizes: tuple[int, ...]
    title_lines: int
    subtitle: int
    body: int
    label: int
    micro: int
    stat_value: int
    avatar: int
    face: int
    qr: int
    icon: int
    gap: int

    @property
    def tracking(self) -> float:
        """Letter spacing for the small uppercase labels."""
        return self.label * 0.12


POSTER_METRICS = Metrics(
    margin=68,
    frame=14,
    card_radius=46,
    panel_radius=30,
    title_sizes=(88, 76, 64, 54),
    title_lines=2,
    subtitle=34,
    body=29,
    label=25,
    micro=21,
    stat_value=46,
    avatar=168,
    face=52,
    qr=232,
    icon=30,
    gap=24,
)

STORY_METRICS = Metrics(
    margin=84,
    frame=16,
    card_radius=54,
    panel_radius=34,
    title_sizes=(104, 90, 76, 64),
    title_lines=3,
    subtitle=40,
    body=34,
    label=29,
    micro=25,
    stat_value=54,
    avatar=220,
    face=62,
    qr=310,
    icon=36,
    gap=30,
)

CARD_METRICS = Metrics(
    margin=52,
    frame=10,
    card_radius=34,
    panel_radius=22,
    title_sizes=(62, 54, 46, 40),
    title_lines=2,
    subtitle=26,
    body=23,
    label=19,
    micro=17,
    stat_value=34,
    avatar=140,
    face=40,
    qr=190,
    icon=22,
    gap=16,
)

METRICS_BY_LAYOUT = {"POSTER": POSTER_METRICS, "STORY": STORY_METRICS, "CARD": CARD_METRICS}


def render_card(request: RenderRequest) -> Image.Image:
    """Draw the card described by `request`. Raises SourceImageError if the
    caller's imagery cannot be decoded; everything else is best effort."""
    card = request.payload
    theme = resolve_card_theme(request)
    metrics = METRICS_BY_LAYOUT[request.layout]

    image = new_canvas(request.size, theme, inset=metrics.frame, radius=metrics.card_radius)
    draw = ImageDraw.Draw(image, "RGBA")

    avatar = _source(card.avatar_base64, card.avatar_url, "avatar", request.request_id)
    cover = _cover(request, theme)

    if request.layout == "CARD":
        _compose_landscape(image, draw, request, theme, metrics, avatar, cover)
    elif request.kind == "SQUAD":
        _compose_squad(image, draw, request, theme, metrics, avatar, cover)
    elif request.kind == "EVENT":
        _compose_event(image, draw, request, theme, metrics, avatar, cover)
    else:
        _compose_user(image, draw, request, theme, metrics, avatar)

    card_border(draw, image.size, metrics.card_radius, metrics.frame, theme.border)
    return image


def resolve_card_theme(request: RenderRequest) -> Theme:
    """The theme a request resolves to, before any drawing happens."""
    return resolve_theme(request.theme, request.kind, request.payload.accent_color)


# --------------------------------------------------------------------------
# Portrait layouts
# --------------------------------------------------------------------------


def _compose_squad(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    request: RenderRequest,
    theme: Theme,
    metrics: Metrics,
    avatar: Image.Image | None,
    cover: Image.Image | None,
) -> None:
    card = request.payload
    assert isinstance(card, SquadCard)
    width = image.size[0]
    margin = metrics.margin
    content_width = width - margin * 2

    band_bottom = _draw_cover(image, cover, theme, metrics)
    _draw_brand_row(draw, image, request, theme, metrics)

    floor = _draw_bottom_block(image, draw, request, theme, metrics)
    panel_top = _draw_squad_panel(image, draw, request, theme, metrics, floor - metrics.gap)
    limit = panel_top - metrics.gap

    avatar_size = metrics.avatar
    avatar_top = band_bottom - round(avatar_size * 0.62)
    paste_avatar(image, _avatar_image(avatar, card.title, avatar_size, theme), (margin, avatar_top), ring=theme.accent)
    cursor = avatar_top + avatar_size + metrics.gap

    chips = _squad_chips(card)
    meta = _squad_meta(card)
    reserved = _reserved_height(
        metrics,
        subtitle=bool(card.subtitle),
        chips=bool(chips),
        meta_rows=1 if meta else 0,
    )

    title_face, title_lines = fit_text(
        draw,
        card.title.upper(),
        sizes=metrics.title_sizes,
        weight="bold",
        max_width=content_width,
        max_lines=_line_budget(limit - cursor - reserved, metrics.title_sizes[0] * 1.3, metrics.title_lines),
    )
    cursor = draw_lines(draw, (margin, cursor), title_lines, title_face, theme.text, spacing=1.02)
    cursor += metrics.gap // 3

    if card.subtitle:
        subtitle_face, subtitle_lines = fit_text(
            draw,
            card.subtitle,
            sizes=(metrics.subtitle, metrics.subtitle - 5),
            weight="regular",
            max_width=content_width,
            max_lines=1,
        )
        if cursor + subtitle_face.line_height <= limit:
            cursor = draw_lines(draw, (margin, cursor), subtitle_lines, subtitle_face, theme.accent)
    cursor += metrics.gap // 2

    cursor = _draw_chip_row(draw, (margin, cursor), chips, theme, metrics, content_width, limit=limit)
    _draw_meta_row(draw, (margin, cursor), meta, theme, metrics, content_width, limit=limit)


def _compose_user(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    request: RenderRequest,
    theme: Theme,
    metrics: Metrics,
    avatar: Image.Image | None,
) -> None:
    """The namecard. No cover art: the face is the hero, and everything else
    hangs off the column beside it."""
    card = request.payload
    assert isinstance(card, UserCard)
    width, _ = image.size
    margin = metrics.margin
    content_width = width - margin * 2

    _draw_brand_row(draw, image, request, theme, metrics)

    floor = _draw_bottom_block(image, draw, request, theme, metrics)

    # The strip is measured now and drawn last. A namecard carries less than a
    # poster - three chips and a one line bio - so bottom anchoring it left a
    # hole in the middle of the card. Whatever room is spare gets split between
    # the content above it and the QR below.
    stats = _user_stats(card)
    strip_bottom = floor - metrics.gap
    strip_top = strip_bottom - (_stat_strip_height(metrics, stacked=True) if stats else 0)
    limit = strip_top - metrics.gap

    avatar_size = round(metrics.avatar * 1.05)
    avatar_top = margin + round(metrics.label * 3.4)
    # The ring carries the tier the way the avatar frame does in the app, so a
    # card and a profile read as the same person at the same rank.
    ring = tier_color(card.level) if card.level is not None else theme.accent
    paste_avatar(image, _avatar_image(avatar, card.title, avatar_size, theme), (margin, avatar_top), ring=ring)

    column_x = margin + avatar_size + metrics.gap * 2
    column_width = width - column_x - margin
    cursor = avatar_top

    tick = round(metrics.subtitle * 1.15) if card.verified else 0
    title_face, title_lines = fit_text(
        draw,
        card.title,
        # A display name is a single line if it can possibly be one, so the
        # sizes start lower here than on a squad or event title.
        sizes=metrics.title_sizes[1:],
        weight="bold",
        max_width=column_width - (tick + metrics.gap if tick else 0),
        max_lines=2,
    )
    title_bottom = draw_lines(draw, (column_x, cursor), title_lines, title_face, theme.text, spacing=1.04)
    if tick:
        badge(
            draw,
            (
                width - margin - tick,
                cursor + (title_face.line_height - tick) / 2,
                width - margin,
                cursor + (title_face.line_height + tick) / 2,
            ),
            theme.accent,
            readable_text(theme.accent),
        )
    cursor = title_bottom + metrics.gap // 4

    if card.handle or card.subtitle:
        handle_face = get_font(metrics.subtitle, "bold")
        handle = card.handle or card.subtitle or ""
        handle_bottom = draw_lines(draw, (column_x, cursor), [handle], handle_face, theme.accent)

        # Level sits beside the handle rather than in the stat strip: it is an
        # identity, not a measurement, and the strip is for countable things.
        if card.level is not None:
            _draw_level_pill(
                draw,
                (column_x + text_width(draw, handle, handle_face) + metrics.gap // 2, cursor),
                card.level,
                metrics,
            )
        cursor = handle_bottom

    meta_face = get_font(metrics.body, "regular")
    if card.location:
        cursor += metrics.gap // 4
        icon_row(
            draw,
            (column_x, cursor),
            [("pin", card.location)],
            meta_face,
            theme.muted,
            icon_size=metrics.icon,
            gap=metrics.gap // 3,
            spacing=metrics.gap,
            icon_fill=theme.accent,
        )
        cursor += meta_face.line_height

    status = card.status_label or ("Active player" if card.level is not None else None)
    if status:
        dot_radius = max(metrics.icon * 0.22, 4)
        status_dot(draw, (column_x + dot_radius * 1.9, cursor + meta_face.line_height * 0.55), dot_radius, theme.accent)
        draw.text((column_x + dot_radius * 4.4, cursor), status, font=meta_face.font, fill=theme.muted)
        cursor += meta_face.line_height

    cursor = max(cursor, avatar_top + avatar_size) + metrics.gap

    chips = [(sport_icon(sport), sport) for sport in card.sports[:3] if sport]
    reserved = _reserved_height(metrics, subtitle=False, chips=bool(chips), meta_rows=0)

    if card.description:
        body_face = get_font(metrics.body, "regular")
        _, lines = fit_text(
            draw,
            card.description,
            sizes=(metrics.body,),
            weight="regular",
            max_width=content_width,
            max_lines=_line_budget(limit - cursor - reserved, body_face.line_height * 1.3, 3),
        )
        if lines and cursor + body_face.line_height <= limit:
            cursor = draw_lines(draw, (margin, cursor), lines, body_face, theme.text, spacing=1.3) + metrics.gap // 2

    if chips:
        cursor = _draw_chip_row(draw, (margin, cursor), chips, theme, metrics, content_width, limit=limit, filled=False)

    if stats:
        slack = max(strip_top - (cursor + metrics.gap * 2), 0)
        _draw_stat_strip(
            draw,
            request,
            theme,
            metrics,
            (margin, strip_bottom - slack // 2, width - margin),
            stacked=True,
            stats=stats,
        )


def _compose_event(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    request: RenderRequest,
    theme: Theme,
    metrics: Metrics,
    avatar: Image.Image | None,
    cover: Image.Image | None,
) -> None:
    card = request.payload
    assert isinstance(card, EventCard)
    width, _ = image.size
    margin = metrics.margin

    band_bottom = _draw_cover(image, cover, theme, metrics)
    _draw_brand_row(draw, image, request, theme, metrics)

    floor = _draw_bottom_block(image, draw, request, theme, metrics)
    strip_top = _draw_stat_strip(
        draw,
        request,
        theme,
        metrics,
        (margin, floor - metrics.gap, width - margin),
    )
    details_bottom = strip_top - metrics.gap
    details_top = _draw_event_details(draw, card, theme, metrics, (margin, details_bottom, width - margin))
    limit = details_top - metrics.gap

    avatar_size = round(metrics.avatar * 0.86)
    avatar_top = band_bottom - round(avatar_size * 0.46)
    paste_avatar(
        image,
        _avatar_image(avatar, card.host_name or card.title, avatar_size, theme),
        (margin, avatar_top),
        ring=theme.accent,
    )

    column_x = margin + avatar_size + metrics.gap
    column_width = width - column_x - margin
    cursor = avatar_top

    host_face = get_font(metrics.subtitle, "regular")
    squad_name = card.squad_name or card.subtitle
    host_rows = (1 if card.host_name else 0) + (1 if squad_name and squad_name != card.host_name else 0)
    reserved = host_rows * host_face.line_height + metrics.gap // 4

    title_face, title_lines = fit_text(
        draw,
        card.title,
        sizes=metrics.title_sizes,
        weight="bold",
        max_width=column_width,
        max_lines=_line_budget(limit - cursor - reserved, metrics.title_sizes[0] * 1.3, 2),
    )
    cursor = draw_lines(draw, (column_x, cursor), title_lines, title_face, theme.text, spacing=1.03)
    cursor += metrics.gap // 4

    host_bold = get_font(metrics.subtitle, "bold")
    if card.host_name and cursor + host_face.line_height <= limit:
        x = float(column_x)
        draw.text((x, cursor), "Hosted by ", font=host_face.font, fill=theme.muted)
        x += text_width(draw, "Hosted by ", host_face)
        draw.text((x, cursor), card.host_name, font=host_bold.font, fill=theme.accent)
        cursor += host_face.line_height

    if squad_name and squad_name != card.host_name and cursor + host_face.line_height <= limit:
        x = float(column_x)
        draw.text((x, cursor), "for ", font=host_face.font, fill=theme.muted)
        x += text_width(draw, "for ", host_face)
        draw.text((x, cursor), squad_name.upper(), font=host_bold.font, fill=theme.accent)


# --------------------------------------------------------------------------
# Landscape layout
# --------------------------------------------------------------------------


def _compose_landscape(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    request: RenderRequest,
    theme: Theme,
    metrics: Metrics,
    avatar: Image.Image | None,
    cover: Image.Image | None,
) -> None:
    """The 1.91:1 link preview.

    Too short for a stacked hero, so it splits: identity on the left, the scan
    block on the right, both centred in their own column.
    """
    card = request.payload
    width, height = image.size
    margin = metrics.margin

    if cover is not None:
        # Darker floor than a portrait band: this photo sits behind the
        # whole card, not just a strip of it.
        cover_wash(image, cover, height, floor=150)
        page = Image.new("RGB", image.size, darken(theme.background_bottom, PAGE_TINT))
        image.paste(page, (0, 0), ImageChops.invert(_corner_mask(image.size, metrics)))

    _draw_brand_row(draw, image, request, theme, metrics)

    top = metrics.frame + margin + round(metrics.label * 2.2)
    bottom = height - metrics.frame - margin

    scan_width = round(metrics.qr * 1.9)
    scan_center = width - margin - scan_width // 2
    column_right = width - margin - scan_width - metrics.gap * 2

    _draw_scan_column(image, draw, request, theme, metrics, scan_center, (top, bottom))

    strip_top = _draw_stat_strip(draw, request, theme, metrics, (margin, bottom, column_right))
    limit = strip_top - metrics.gap

    avatar_size = metrics.avatar
    column_x = margin + avatar_size + metrics.gap
    column_width = column_right - column_x

    title_face, title_lines = fit_text(
        draw,
        card.title,
        sizes=metrics.title_sizes,
        weight="bold",
        max_width=column_width,
        max_lines=2,
    )
    meta = _meta_entries(card)
    meta_face = get_font(metrics.body, "regular")
    subtitle_face = get_font(metrics.subtitle, "bold")

    block = title_face.line_height * len(title_lines)
    if card.subtitle:
        block += subtitle_face.line_height
    if meta:
        block += round(meta_face.line_height * 1.4)

    cursor = max(top, round((top + limit - block) / 2))
    paste_avatar(
        image,
        _avatar_image(avatar, card.title, avatar_size, theme),
        (margin, cursor + round((block - avatar_size) / 2) if block > avatar_size else cursor),
        ring=theme.accent,
    )

    cursor = draw_lines(draw, (column_x, cursor), title_lines, title_face, theme.text, spacing=1.03)
    if card.subtitle:
        cursor = draw_lines(draw, (column_x, cursor), [card.subtitle], subtitle_face, theme.accent)
    if meta:
        icon_row(
            draw,
            (column_x, cursor + metrics.gap // 3),
            meta[:2],
            meta_face,
            theme.muted,
            icon_size=metrics.icon,
            gap=metrics.gap // 3,
            spacing=metrics.gap,
            icon_fill=theme.accent,
        )


def _draw_scan_column(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    request: RenderRequest,
    theme: Theme,
    metrics: Metrics,
    center_x: int,
    bounds: tuple[int, int],
) -> None:
    """Call to action, QR plate and link, centred in the right hand column."""
    card = request.payload
    top, bottom = bounds

    label_face = get_font(metrics.micro, "bold")
    url_face = get_font(metrics.micro, "bold")
    padding = metrics.gap // 2

    url = _display_url(card.share_url) or settings.render_brand_url
    if not card.share_url:
        draw.text(
            (center_x - text_width(draw, url, url_face) / 2, (top + bottom) / 2),
            url,
            font=url_face.font,
            fill=theme.accent,
        )
        return

    cta = (card.cta_label or CTA_LABELS.get(request.kind, "SCAN ME")).upper()
    block = (
        label_face.line_height + metrics.gap // 2 + metrics.qr + padding * 2 + metrics.gap // 2 + url_face.line_height
    )
    cursor = round((top + bottom - block) / 2)

    tracked_text(
        draw,
        (center_x - tracked_width(draw, cta, label_face, metrics.tracking) / 2, cursor),
        cta,
        label_face,
        theme.accent,
        tracking=metrics.tracking,
    )
    cursor += label_face.line_height + metrics.gap // 2 + padding

    cursor = qr_panel(
        image,
        draw,
        card.share_url,
        center_x,
        cursor,
        metrics.qr,
        padding=padding,
        radius=metrics.panel_radius // 2,
    )
    draw.text(
        (center_x - text_width(draw, url, url_face) / 2, cursor + metrics.gap // 2),
        url,
        font=url_face.font,
        fill=theme.accent,
    )


# --------------------------------------------------------------------------
# Shared blocks
# --------------------------------------------------------------------------


def _draw_brand_row(
    draw: ImageDraw.ImageDraw,
    image: Image.Image,
    request: RenderRequest,
    theme: Theme,
    metrics: Metrics,
) -> None:
    """Brand mark on the left, card kind on the right."""
    width = image.size[0]
    margin = metrics.margin
    top = metrics.frame + metrics.margin // 2

    brand_face = get_font(round(metrics.label * 1.35), "bold")
    tracked_text(
        draw,
        (margin, top),
        settings.render_brand_name.upper(),
        brand_face,
        theme.text,
        tracking=brand_face.size * 0.06,
    )

    label_face = get_font(metrics.micro, "bold")
    label = KIND_LABELS.get(request.kind, request.kind)
    label_width = round(tracked_width(draw, label, label_face, metrics.tracking)) + metrics.gap * 2
    chip(
        draw,
        (width - margin - label_width, top - metrics.gap // 3),
        label,
        label_face,
        fill=with_alpha(theme.accent, 245),
        text_color=theme.on_accent,
        padding=(metrics.gap, metrics.gap // 2),
        tracking=metrics.tracking,
    )


def _draw_cover(
    image: Image.Image,
    cover: Image.Image | None,
    theme: Theme,
    metrics: Metrics,
) -> int:
    """Hero band across the top of the card. Returns the y it ends at, which is
    what the avatar hangs off."""
    width, height = image.size
    band_bottom = metrics.frame + round(height * 0.235)
    if cover is None:
        return band_bottom

    box = (metrics.frame, metrics.frame, width - metrics.frame, band_bottom)
    hero_cover(image, cover, box, theme, clip=_corner_mask(image.size, metrics).crop(box))
    return band_bottom


def _corner_mask(size: tuple[int, int], metrics: Metrics) -> Image.Image:
    return rounded_mask(size, metrics.card_radius, metrics.frame)


def _draw_bottom_block(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    request: RenderRequest,
    theme: Theme,
    metrics: Metrics,
) -> int:
    """Call to action, QR plate, link and affordance row, anchored to the floor
    of the card. Returns the y where the block starts."""
    card = request.payload
    width, height = image.size
    center = width // 2
    bottom = height - metrics.frame - metrics.margin

    label_face = get_font(metrics.label, "bold")
    url_face = get_font(metrics.label, "bold")
    action_face = get_font(metrics.micro, "regular")

    actions = _actions(request)
    action_entries = [(_action_icon(action), action) for action in actions]
    action_height = action_face.line_height if action_entries else 0
    if action_entries:
        row_width = icon_row_width(
            draw,
            action_entries,
            action_face,
            icon_size=metrics.icon,
            gap=metrics.gap // 4,
            spacing=metrics.gap,
        )
        icon_row(
            draw,
            (center - row_width / 2, bottom - action_height),
            action_entries,
            action_face,
            theme.muted,
            icon_size=metrics.icon,
            gap=metrics.gap // 4,
            spacing=metrics.gap,
        )

    url = _display_url(card.share_url) or settings.render_brand_url
    url_bottom = bottom - action_height - (metrics.gap // 2 if action_entries else 0)
    draw.text(
        (center - text_width(draw, url, url_face) / 2, url_bottom - url_face.line_height),
        url,
        font=url_face.font,
        fill=theme.accent,
    )

    top = url_bottom - url_face.line_height - metrics.gap // 2

    if card.share_url:
        qr_top = top - metrics.qr - metrics.gap // 2
        qr_panel(
            image,
            draw,
            card.share_url,
            center,
            qr_top,
            metrics.qr,
            padding=metrics.gap // 2,
            radius=metrics.panel_radius // 2,
        )
        top = qr_top - metrics.gap // 2 - metrics.gap

        cta = (card.cta_label or CTA_LABELS.get(request.kind, "SCAN ME")).upper()
        cta_width = tracked_width(draw, cta, label_face, metrics.tracking)
        top -= label_face.line_height
        tracked_text(draw, (center - cta_width / 2, top), cta, label_face, theme.accent, tracking=metrics.tracking)

    footer_note = card.footer_note
    if footer_note:
        note_face = get_font(metrics.micro, "regular")
        top -= note_face.line_height + metrics.gap // 3
        draw.text(
            (center - text_width(draw, footer_note, note_face) / 2, top),
            footer_note,
            font=note_face.font,
            fill=theme.muted,
        )

    return top


def _draw_squad_panel(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    request: RenderRequest,
    theme: Theme,
    metrics: Metrics,
    bottom: int,
) -> int:
    """The squad detail strip: members, founded, captain, and the faces."""
    card = request.payload
    assert isinstance(card, SquadCard)
    width = image.size[0]
    margin = metrics.margin

    columns: list[tuple[str | None, str, str]] = [
        (stat.icon or stat_icon(stat.label), stat.value, stat.label) for stat in card.stats[:3]
    ]
    if not columns and card.member_count is not None:
        columns.append(("users", str(card.member_count), "Members"))
    if card.founded_year and not any("found" in label.lower() or "since" in label.lower() for _, _, label in columns):
        columns.append(("calendar", str(card.founded_year), "Founded"))
    if card.captain_name:
        columns.append(("shield", _initials(card.captain_name), "Captain"))

    faces = _member_faces(card, metrics.face, request.request_id)
    overflow = max((card.member_count or 0) - len(faces), 0) if faces else 0

    columns = columns[: 3 if faces else 4]
    if not columns and not faces:
        return bottom

    height = round(metrics.stat_value * 2.5)
    box = (margin, bottom - height, width - margin, bottom)
    panel(draw, box, metrics.panel_radius, theme.panel, theme.panel_border)

    slots = len(columns) + (1 if faces else 0)
    column_width = (box[2] - box[0]) / slots

    for index, (icon, value, label) in enumerate(columns):
        left = box[0] + column_width * index
        if index:
            divider(draw, (round(left), box[1] + metrics.gap, round(left), box[3] - metrics.gap), theme)
        _draw_stat_cell(draw, (left, box[1], left + column_width, box[3]), icon, value, label, theme, metrics)

    if faces:
        left = box[0] + column_width * len(columns)
        divider(draw, (round(left), box[1] + metrics.gap, round(left), box[3] - metrics.gap), theme)
        stack_width = (len(faces) + (1 if overflow else 0) - 1) * round(metrics.face * 0.68) + metrics.face
        avatar_stack(
            image,
            faces,
            (round(left + (column_width - stack_width) / 2), round((box[1] + box[3]) / 2 - metrics.face / 2)),
            metrics.face,
            theme,
            overflow=overflow,
        )

    return box[1]


def _stat_strip_height(metrics: Metrics, *, stacked: bool = False) -> int:
    return round(metrics.stat_value * (3.0 if stacked else 2.5))


def _draw_stat_strip(
    draw: ImageDraw.ImageDraw,
    request: RenderRequest,
    theme: Theme,
    metrics: Metrics,
    bounds: tuple[int, int, int],
    *,
    stacked: bool = False,
    stats: Sequence[Stat] | None = None,
) -> int:
    """Panel of `stats` from the payload. Returns the y it starts at."""
    card = request.payload
    left, bottom, right = bounds
    stats = list(stats if stats is not None else card.stats)[:4]
    if not stats:
        return bottom

    height = _stat_strip_height(metrics, stacked=stacked)
    box = (left, bottom - height, right, bottom)
    panel(draw, box, metrics.panel_radius, theme.panel, theme.panel_border)

    column_width = (right - left) / len(stats)
    for index, stat in enumerate(stats):
        column_left = left + column_width * index
        if index:
            divider(draw, (round(column_left), box[1] + metrics.gap, round(column_left), box[3] - metrics.gap), theme)
        _draw_stat_cell(
            draw,
            (column_left, box[1], column_left + column_width, box[3]),
            stat.icon or stat_icon(stat.label),
            stat.value,
            stat.label,
            theme,
            metrics,
            stacked=stacked,
        )

    return box[1]


def _draw_stat_cell(
    draw: ImageDraw.ImageDraw,
    box: tuple[float, float, float, float],
    icon: str | None,
    value: str,
    label: str,
    theme: Theme,
    metrics: Metrics,
    *,
    stacked: bool = False,
) -> None:
    """One column of a detail panel: a number with its unit under it.

    `stacked` puts the icon above the number (the player card's four up grid);
    otherwise it sits beside it, which reads better in a wider column.
    """
    x0, y0, x1, y1 = box
    center_x = (x0 + x1) / 2
    value_face = get_font(metrics.stat_value, "bold")
    label_face = get_font(metrics.micro, "bold")

    caption = label.upper()
    caption_width = tracked_width(draw, caption, label_face, metrics.tracking * 0.6)
    value_width = text_width(draw, value, value_face)
    icon_size = round(metrics.icon * 0.95)

    if stacked and icon:
        block = icon_size + metrics.gap // 3 + value_face.line_height + label_face.line_height
        top = (y0 + y1) / 2 - block / 2
        draw_icon(draw, icon, (center_x - icon_size / 2, top, center_x + icon_size / 2, top + icon_size), theme.accent)
        value_top = top + icon_size + metrics.gap // 3
    else:
        block = value_face.line_height + label_face.line_height
        value_top = (y0 + y1) / 2 - block / 2
        if icon:
            row_width = icon_size + metrics.gap // 3 + value_width
            icon_left = center_x - row_width / 2
            draw_icon(
                draw,
                icon,
                (
                    icon_left,
                    value_top + (value_face.line_height - icon_size) / 2,
                    icon_left + icon_size,
                    value_top + (value_face.line_height + icon_size) / 2,
                ),
                theme.accent,
            )
            draw.text(
                (icon_left + icon_size + metrics.gap // 3, value_top), value, font=value_face.font, fill=theme.text
            )
            _draw_caption(
                draw, center_x, value_top + value_face.line_height, caption, caption_width, label_face, theme, metrics
            )
            return

    draw.text((center_x - value_width / 2, value_top), value, font=value_face.font, fill=theme.text)
    _draw_caption(
        draw, center_x, value_top + value_face.line_height, caption, caption_width, label_face, theme, metrics
    )


def _draw_caption(
    draw: ImageDraw.ImageDraw,
    center_x: float,
    top: float,
    caption: str,
    caption_width: float,
    face: Typeface,
    theme: Theme,
    metrics: Metrics,
) -> None:
    tracked_text(draw, (center_x - caption_width / 2, top), caption, face, theme.muted, tracking=metrics.tracking * 0.6)


def _draw_event_details(
    draw: ImageDraw.ImageDraw,
    card: EventCard,
    theme: Theme,
    metrics: Metrics,
    bounds: tuple[int, int, int],
) -> int:
    """Two column panel of what/when/where. Returns the y it starts at."""
    left, bottom, right = bounds
    first, second = _event_detail_columns(card)
    if not first and not second:
        return bottom

    face = get_font(metrics.body, "regular")
    rows = max(len(first), len(second))
    row_step = round(face.line_height * 1.55)
    height = row_step * rows + metrics.gap * 2 - (row_step - face.line_height)

    box = (left, bottom - height, right, bottom)
    panel(draw, box, metrics.panel_radius, theme.panel, theme.panel_border)

    column_width = (right - left) / 2
    for index, column in enumerate((first, second)):
        column_left = left + column_width * index + metrics.gap
        text_left = column_left + metrics.icon + metrics.gap // 3
        # A full postal address is longer than half a card. Clip it here rather
        # than at the source: the venue is worth as much of its own text as the
        # column can hold, and the column is what knows how much that is.
        available = left + column_width * (index + 1) - text_left - metrics.gap
        top = box[1] + metrics.gap

        for icon, value in column:
            lines = value.split("\n")
            icon_top = top + (face.line_height - metrics.icon) / 2
            draw_icon(
                draw,
                icon,
                (column_left, icon_top, column_left + metrics.icon, icon_top + metrics.icon),
                theme.accent,
            )
            for line_index, line in enumerate(lines[:2]):
                draw.text(
                    (text_left, top + line_index * face.line_height),
                    ellipsize(draw, line, face, available),
                    font=face.font,
                    fill=theme.text if line_index == 0 else theme.muted,
                )
            top += row_step + face.line_height * (min(len(lines), 2) - 1)

    return box[1]


def _draw_chip_row(
    draw: ImageDraw.ImageDraw,
    origin: tuple[int, int],
    labels: Sequence[str | tuple[str | None, str]],
    theme: Theme,
    metrics: Metrics,
    max_width: int,
    *,
    limit: int | None = None,
    filled: bool = True,
) -> int:
    """One row of pills, clipped at `max_width`. Returns the y below the row."""
    if not labels:
        return origin[1]

    face = get_font(metrics.label, "bold")
    x, y = origin
    height = face.line_height + metrics.gap
    if limit is not None and y + height > limit:
        return y

    padding = (metrics.gap - 2, metrics.gap // 2)
    tracking = metrics.tracking * 0.5

    for entry in labels:
        icon, label = entry if isinstance(entry, tuple) else (None, entry)
        text = label.upper()
        width = _chip_width(draw, text, face, icon=icon, padding=padding, tracking=tracking)
        if x + width > origin[0] + max_width:
            break
        chip(
            draw,
            (x, y),
            text,
            face,
            fill=with_alpha(theme.accent, 240) if filled else theme.chip_fill,
            text_color=theme.on_accent if filled else theme.text,
            padding=padding,
            outline=None if filled else theme.panel_border,
            icon=icon,
            tracking=tracking,
        )
        x += width + metrics.gap // 2

    return y + height + metrics.gap // 3


def _chip_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    face: Typeface,
    *,
    icon: str | None,
    padding: tuple[int, int],
    tracking: float,
) -> int:
    """What `chip` will occupy, without drawing it."""
    width = round(tracked_width(draw, text, face, tracking)) + padding[0] * 2
    if icon:
        width += round(face.size * 1.05) + round(face.size * 0.42)
    return width


def _draw_meta_row(
    draw: ImageDraw.ImageDraw,
    origin: tuple[int, int],
    entries: Sequence[tuple[str | None, str]],
    theme: Theme,
    metrics: Metrics,
    max_width: int,
    *,
    limit: int | None = None,
) -> int:
    """Location / language / privacy under a title, wrapped onto a second line
    when the first will not hold them."""
    if not entries:
        return origin[1]

    face = get_font(metrics.body, "regular")
    x, y = origin
    if limit is not None and y + face.line_height > limit:
        return y

    row: list[tuple[str | None, str]] = []
    for entry in entries:
        candidate = [*row, entry]
        width = icon_row_width(
            draw,
            candidate,
            face,
            icon_size=metrics.icon,
            gap=metrics.gap // 3,
            spacing=metrics.gap * 2,
        )
        if width > max_width and row:
            y = _flush_meta_row(draw, (x, y), row, face, theme, metrics)
            row = [entry]
            if limit is not None and y + face.line_height > limit:
                return y
        else:
            row = candidate

    if row:
        y = _flush_meta_row(draw, (x, y), row, face, theme, metrics)
    return y


def _flush_meta_row(
    draw: ImageDraw.ImageDraw,
    origin: tuple[int, int],
    entries: Sequence[tuple[str | None, str]],
    face: Typeface,
    theme: Theme,
    metrics: Metrics,
) -> int:
    icon_row(
        draw,
        origin,
        entries,
        face,
        theme.muted,
        icon_size=metrics.icon,
        gap=metrics.gap // 3,
        spacing=metrics.gap * 2,
        icon_fill=theme.accent,
    )
    return origin[1] + round(face.line_height * 1.35)


# --------------------------------------------------------------------------
# Payload to content
# --------------------------------------------------------------------------


def _draw_level_pill(
    draw: ImageDraw.ImageDraw,
    origin: tuple[float, float],
    level: int,
    metrics: Metrics,
) -> None:
    """ "LV 12" in the colour of its tier, matching the badge in the app."""
    face = get_font(metrics.micro, "bold")
    color = tier_color(level)
    chip(
        draw,
        (round(origin[0]), round(origin[1] + (metrics.subtitle - face.line_height) * 0.35)),
        f"LV {level}",
        face,
        fill=with_alpha(color, 245),
        text_color=readable_text(color),
        padding=(metrics.gap // 2, metrics.gap // 6),
        icon="shield",
        tracking=metrics.tracking * 0.4,
    )


def _user_stats(card: UserCard) -> list[Stat]:
    """The four up strip, minus anything the card already says elsewhere.

    The backend leads its user stats with Level, which is now a badge on the
    handle line; printing it twice on one card just wastes a column.
    """
    if card.level is None:
        return list(card.stats)
    return [stat for stat in card.stats if "level" not in stat.label.strip().lower()]


def _squad_chips(card: SquadCard) -> list[tuple[str | None, str]]:
    """Pills above the squad's meta line: sport and how open it is.

    Only the squad card uses pills for this. The player card builds its own row
    from `sports`, and the event card puts the same facts in its detail panel,
    where they have room for a value each.
    """
    chips: list[tuple[str | None, str]] = []
    if card.sport:
        chips.append((sport_icon(card.sport), card.sport))
    if card.privacy:
        chips.append((None, card.privacy))
    return chips[:3]


def _squad_meta(card: SquadCard) -> list[tuple[str | None, str]]:
    entries: list[tuple[str | None, str]] = []
    if card.location:
        entries.append(("pin", card.location))
    if card.language:
        entries.append(("globe", card.language))
    if card.privacy:
        private = "private" in card.privacy.lower()
        entries.append(("lock" if private else "unlock", "Private" if private else "Public"))
    return entries


def _meta_entries(card: BaseCard) -> list[tuple[str | None, str]]:
    """Secondary detail used by the landscape layout."""
    entries: list[tuple[str | None, str]] = []

    if isinstance(card, EventCard):
        if card.starts_at is not None:
            entries.append(("calendar", format_event_date(card.starts_at)))
        venue = card.venue or card.location
        if venue:
            entries.append(("pin", venue))
        if card.host_name:
            entries.append(("shield", f"Hosted by {card.host_name}"))
    else:
        if isinstance(card, SquadCard) and card.member_count is not None:
            entries.append(("users", f"{card.member_count} members"))
        if card.location:
            entries.append(("pin", card.location))

    return entries[:3]


def _event_detail_columns(card: EventCard) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """What goes in the event's two column panel, left column first."""
    first: list[tuple[str, str]] = []
    second: list[tuple[str, str]] = []

    if card.starts_at is not None:
        first.append(("calendar", format_event_day(card.starts_at)))
        first.append(("clock", format_event_time(card.starts_at, card.ends_at)))
    if card.sport:
        first.append((sport_icon(card.sport), card.sport))

    venue = card.venue or card.location
    if venue:
        second.append(("pin", _split_venue(venue)))
    if card.format_label:
        second.append(("jersey", card.format_label))
    if card.audience_label:
        second.append(("users", card.audience_label))
    elif card.spots_left is not None:
        second.append(("users", f"{card.spots_left} spots left" if card.spots_left else "Fully booked"))

    return first, second


def _split_venue(venue: str) -> str:
    """Venue over two lines at the first comma: "KLCQ Park" then the address."""
    head, separator, tail = venue.partition(",")
    if not separator or len(head) < 3:
        return venue
    return f"{head.strip()}\n{tail.strip()}"


def _actions(request: RenderRequest) -> list[str]:
    """The row under the link, and only when a caller asked for one.

    There used to be a default per kind ("Add to calendar - Share event"). On a
    flat image they are not affordances, they are a caption describing controls
    that are not there, and the card reads cleaner ending on its link.
    """
    return [action for action in request.payload.actions if action.strip()][:3]


def _action_icon(action: str) -> str | None:
    text = action.strip().lower()
    for needle, name in ACTION_ICONS:
        if needle in text:
            return name
    return None


def _initials(name: str) -> str:
    return "".join(word[0] for word in name.split()[:2] if word).upper() or "?"


def _reserved_height(metrics: Metrics, *, subtitle: bool, chips: bool, meta_rows: int) -> int:
    """Height to keep clear under a title for the rows that follow it.

    Fitting the title first and discovering afterwards that nothing else fits
    is how the chip and meta rows silently disappeared on a long squad name.
    """
    height = metrics.gap // 2
    if subtitle:
        height += round(metrics.subtitle * 1.28) + metrics.gap // 2
    if chips:
        height += round(metrics.label * 1.28) + metrics.gap + metrics.gap // 2
    height += meta_rows * round(metrics.body * 1.28 * 1.35)
    return height


def _line_budget(available: float, line_height: float, ceiling: int) -> int:
    """How many lines of `line_height` fit in `available` pixels, at least one."""
    return max(min(int(available // line_height), ceiling), 1)


def _display_url(url: str | None) -> str | None:
    if not url:
        return None
    trimmed = url.split("://", 1)[-1].rstrip("/").removeprefix("www.")
    return trimmed[:60]


# --------------------------------------------------------------------------
# Imagery
# --------------------------------------------------------------------------


def _source(
    base64_data: str | None,
    url: str | None,
    label: str,
    request_id: str,
) -> Image.Image | None:
    """Load one piece of caller supplied imagery.

    A card without the user's photo still gets shared; a card that failed to
    render does not. So unless `render_strict_images` says otherwise, a bad or
    unreachable image drops to the generated fallback and is logged.
    """
    try:
        return load_source(base64_data, url)
    except SourceImageError as error:
        if settings.render_strict_images:
            raise
        logger.warning("Dropping %s for request %s: %s", label, request_id, error)
        return None


def _cover(request: RenderRequest, theme: Theme) -> Image.Image | None:
    """The banner, or generated art when the squad or event has none."""
    card = request.payload
    if request.kind not in COVER_KINDS:
        return None

    cover = _source(card.cover_base64, card.cover_url, "cover", request.request_id)
    if cover is not None:
        return cover

    width, height = request.size
    sport = card.sport if isinstance(card, (SquadCard, EventCard)) else None
    return default_cover(request.kind, sport, (width, max(round(height * 0.30), 1)), theme)


def _member_faces(card: SquadCard, size: int, request_id: str) -> list[Image.Image]:
    """Circular thumbnails for the "+N" stack, capped at three."""
    faces: list[Image.Image] = []

    inline = list(card.member_avatars_base64)
    urls = list(card.member_avatar_urls)
    for index in range(max(len(inline), len(urls))):
        if len(faces) >= 3:
            break
        source = _source(
            inline[index] if index < len(inline) else None,
            urls[index] if index < len(urls) else None,
            "member avatar",
            request_id,
        )
        if source is not None:
            faces.append(circle_image(source, size))

    return faces


def _avatar_image(source: Image.Image | None, title: str, size: int, theme: Theme) -> Image.Image:
    if source is None:
        return initials_avatar(title, size, theme)
    return circle_image(source, size)


# --------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------


def format_event_date(value: datetime) -> str:
    """Formats as `SAT 12 SEP · 7:30 PM`, in whatever offset the backend sent."""
    return f"{value.strftime('%a %d %b').upper()} · {_clock(value)}"


def format_event_day(value: datetime) -> str:
    """`Thu, 20 Aug 2026`."""
    return value.strftime("%a, %d %b %Y").replace(" 0", " ")


def format_event_time(start: datetime, end: datetime | None) -> str:
    if end is None:
        return _clock(start)
    return f"{_clock(start)} – {_clock(end)}"


def _clock(value: datetime) -> str:
    return value.strftime("%I:%M %p").lstrip("0")
