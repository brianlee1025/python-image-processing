"""Line icons drawn with Pillow primitives.

The cards are covered in small pictograms - a pin before a venue, a clock
before a time, a ball before a sport - and none of them can be text. System
fonts render emoji as tofu boxes, and shipping an emoji font to draw a dozen
glyphs costs more megabytes than the whole service. So they are drawn.

Every icon fills a square box and takes the same arguments, which is what lets
layout code treat "pin" and "clock" as interchangeable strings that arrive in
a payload.
"""

from collections.abc import Callable
from math import cos, radians, sin

from PIL import ImageDraw

from .palette import RGB, RGBA, with_alpha

Box = tuple[float, float, float, float]

# Sport names arrive from the database in whatever case a user typed, so the
# lookup is lowercased and substring matched: "Beach volleyball" finds "volley".
SPORT_ICONS: tuple[tuple[str, str], ...] = (
    ("futsal", "ball"),
    ("foot", "ball"),
    ("soccer", "ball"),
    ("basket", "basketball"),
    ("volley", "ball"),
    ("badminton", "racket"),
    ("tennis", "racket"),
    ("squash", "racket"),
    ("padel", "racket"),
    ("pickle", "racket"),
    ("run", "run"),
    ("jog", "run"),
    ("marathon", "run"),
    ("cycl", "bike"),
    ("bike", "bike"),
    ("swim", "swim"),
    ("gym", "dumbbell"),
    ("lift", "dumbbell"),
    ("fitness", "dumbbell"),
    ("yoga", "yoga"),
    ("hike", "flag"),
    ("climb", "flag"),
    ("golf", "flag"),
)

# Stat labels the backend already sends, mapped to the pictogram drawn above
# the number. Unknown labels simply get no icon.
STAT_ICONS: tuple[tuple[str, str], ...] = (
    ("member", "users"),
    ("squad", "users"),
    ("going", "users"),
    ("connection", "users"),
    ("friend", "users"),
    ("attend", "users"),
    ("spot", "user"),
    ("capacity", "user"),
    ("event", "calendar"),
    ("game", "calendar"),
    ("match", "calendar"),
    ("weekly", "calendar"),
    ("since", "calendar"),
    ("founded", "calendar"),
    ("joined", "calendar"),
    ("duration", "clock"),
    ("time", "clock"),
    ("price", "tag"),
    ("fee", "tag"),
    ("cost", "tag"),
    ("level", "bolt"),
    ("xp", "bolt"),
    ("streak", "bolt"),
    ("win", "trophy"),
    ("rank", "trophy"),
    ("captain", "shield"),
    ("leader", "shield"),
    ("host", "shield"),
)


def sport_icon(sport: str | None) -> str:
    """Pictogram for a sport name, falling back to a generic ball."""
    if not sport:
        return "ball"
    text = sport.strip().lower()
    for needle, name in SPORT_ICONS:
        if needle in text:
            return name
    return "ball"


def stat_icon(label: str | None) -> str | None:
    if not label:
        return None
    text = label.strip().lower()
    for needle, name in STAT_ICONS:
        if needle in text:
            return name
    return None


def draw_icon(
    draw: ImageDraw.ImageDraw,
    name: str,
    box: Box,
    color: RGB | RGBA,
    *,
    width: int | None = None,
) -> None:
    """Draw `name` inside `box`.

    An unknown name draws nothing rather than raising: an icon is decoration,
    and a payload should not be able to fail a render by naming a sport nobody
    has drawn yet.
    """
    painter = _ICONS.get(name)
    if painter is None:
        return

    x0, y0, x1, y1 = box
    size = min(x1 - x0, y1 - y0)
    stroke = width if width is not None else max(round(size * 0.11), 2)

    # Square and centre the box so an icon never stretches with its slot.
    center_x, center_y = (x0 + x1) / 2, (y0 + y1) / 2
    half = size / 2
    painter(draw, (center_x - half, center_y - half, center_x + half, center_y + half), color, stroke)


def _pin(draw: ImageDraw.ImageDraw, box: Box, color: RGB | RGBA, stroke: int) -> None:
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    draw.ellipse(
        (x0 + width * 0.14, y0 + height * 0.04, x1 - width * 0.14, y0 + height * 0.68), outline=color, width=stroke
    )
    draw.polygon(
        [
            (x0 + width * 0.30, y0 + height * 0.56),
            (x1 - width * 0.30, y0 + height * 0.56),
            (x0 + width * 0.50, y1 - height * 0.02),
        ],
        fill=color,
    )
    dot = width * 0.12
    center_x, center_y = x0 + width * 0.5, y0 + height * 0.34
    draw.ellipse((center_x - dot, center_y - dot, center_x + dot, center_y + dot), fill=color)


def _globe(draw: ImageDraw.ImageDraw, box: Box, color: RGB | RGBA, stroke: int) -> None:
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    draw.ellipse(box, outline=color, width=stroke)
    draw.line((x0, y0 + height * 0.5, x1, y0 + height * 0.5), fill=color, width=max(stroke - 1, 1))
    draw.arc((x0 + width * 0.28, y0, x1 - width * 0.28, y1), 0, 360, fill=color, width=max(stroke - 1, 1))


def _lock(
    draw: ImageDraw.ImageDraw,
    box: Box,
    color: RGB | RGBA,
    stroke: int,
    *,
    shackle: Box | None = None,
) -> None:
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    draw.rounded_rectangle(
        (x0 + width * 0.10, y0 + height * 0.42, x1 - width * 0.10, y1 - height * 0.06),
        radius=max(round(width * 0.16), 2),
        outline=color,
        width=stroke,
    )
    arc = shackle or (x0 + width * 0.26, y0 + height * 0.08, x1 - width * 0.26, y0 + height * 0.60)
    draw.arc(arc, 180, 360, fill=color, width=stroke)
    if shackle is None:
        # Closed: the shackle legs run down into the body.
        for x in (arc[0], arc[2]):
            draw.line((x, (arc[1] + arc[3]) * 0.5, x, y0 + height * 0.44), fill=color, width=stroke)


def _unlock(draw: ImageDraw.ImageDraw, box: Box, color: RGB | RGBA, stroke: int) -> None:
    """Same padlock with the shackle swung up and to the left, which is how a
    public squad is marked."""
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    _lock(
        draw, box, color, stroke, shackle=(x0 + width * 0.02, y0 + height * 0.06, x0 + width * 0.50, y0 + height * 0.56)
    )
    draw.line((x0 + width * 0.02, y0 + height * 0.31, x0 + width * 0.02, y0 + height * 0.44), fill=color, width=stroke)


def _user(draw: ImageDraw.ImageDraw, box: Box, color: RGB | RGBA, stroke: int) -> None:
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    draw.ellipse(
        (x0 + width * 0.28, y0 + height * 0.06, x1 - width * 0.28, y0 + height * 0.50), outline=color, width=stroke
    )
    draw.arc(
        (x0 + width * 0.10, y0 + height * 0.56, x1 - width * 0.10, y1 + height * 0.46),
        180,
        360,
        fill=color,
        width=stroke,
    )


def _users(draw: ImageDraw.ImageDraw, box: Box, color: RGB | RGBA, stroke: int) -> None:
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0

    # Back figure first, so the front one overlaps it the way a group reads.
    draw.ellipse(
        (x0 + width * 0.50, y0 + height * 0.12, x1 - width * 0.04, y0 + height * 0.48),
        outline=color,
        width=max(stroke - 1, 1),
    )
    draw.arc(
        (x0 + width * 0.40, y0 + height * 0.54, x1 + width * 0.06, y1 + height * 0.40),
        200,
        340,
        fill=color,
        width=max(stroke - 1, 1),
    )
    draw.ellipse(
        (x0 + width * 0.06, y0 + height * 0.08, x0 + width * 0.52, y0 + height * 0.50),
        outline=color,
        width=stroke,
    )
    draw.arc(
        (x0 - width * 0.02, y0 + height * 0.56, x0 + width * 0.60, y1 + height * 0.42),
        180,
        360,
        fill=color,
        width=stroke,
    )


def _calendar(draw: ImageDraw.ImageDraw, box: Box, color: RGB | RGBA, stroke: int) -> None:
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    draw.rounded_rectangle(
        (x0 + width * 0.06, y0 + height * 0.16, x1 - width * 0.06, y1 - height * 0.06),
        radius=max(round(width * 0.12), 2),
        outline=color,
        width=stroke,
    )
    draw.line(
        (x0 + width * 0.06, y0 + height * 0.38, x1 - width * 0.06, y0 + height * 0.38),
        fill=color,
        width=max(stroke - 1, 1),
    )
    for offset in (0.30, 0.70):
        x = x0 + width * offset
        draw.line((x, y0 + height * 0.04, x, y0 + height * 0.26), fill=color, width=stroke)

    dot = width * 0.06
    for column in (0.30, 0.50, 0.70):
        center_x, center_y = x0 + width * column, y0 + height * 0.62
        draw.ellipse((center_x - dot, center_y - dot, center_x + dot, center_y + dot), fill=color)


def _calendar_x(draw: ImageDraw.ImageDraw, box: Box, color: RGB | RGBA, stroke: int) -> None:
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    draw.rounded_rectangle(
        (x0 + width * 0.06, y0 + height * 0.16, x1 - width * 0.06, y1 - height * 0.06),
        radius=max(round(width * 0.12), 2),
        outline=color,
        width=stroke,
    )
    draw.line(
        (x0 + width * 0.06, y0 + height * 0.38, x1 - width * 0.06, y0 + height * 0.38),
        fill=color,
        width=max(stroke - 1, 1),
    )
    for offset in (0.30, 0.70):
        x = x0 + width * offset
        draw.line((x, y0 + height * 0.04, x, y0 + height * 0.26), fill=color, width=stroke)

    draw.line((x0 + width * 0.34, y0 + height * 0.54, x1 - width * 0.34, y1 - height * 0.22), fill=color, width=stroke)
    draw.line((x1 - width * 0.34, y0 + height * 0.54, x0 + width * 0.34, y1 - height * 0.22), fill=color, width=stroke)


def _clock(draw: ImageDraw.ImageDraw, box: Box, color: RGB | RGBA, stroke: int) -> None:
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    draw.ellipse(box, outline=color, width=stroke)
    center_x, center_y = x0 + width * 0.5, y0 + height * 0.5
    draw.line((center_x, center_y, center_x, center_y - height * 0.28), fill=color, width=stroke)
    draw.line((center_x, center_y, center_x + width * 0.22, center_y), fill=color, width=stroke)


def _shield(draw: ImageDraw.ImageDraw, box: Box, color: RGB | RGBA, stroke: int) -> None:
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    draw.polygon(
        [
            (x0 + width * 0.50, y0 + height * 0.04),
            (x1 - width * 0.08, y0 + height * 0.22),
            (x1 - width * 0.16, y0 + height * 0.64),
            (x0 + width * 0.50, y1 - height * 0.04),
            (x0 + width * 0.16, y0 + height * 0.64),
            (x0 + width * 0.08, y0 + height * 0.22),
        ],
        outline=color,
        width=stroke,
    )


def _ball(draw: ImageDraw.ImageDraw, box: Box, color: RGB | RGBA, stroke: int) -> None:
    """Football: a circle, a centre pentagon and three seams, which is all the
    eye needs at 30 px."""
    x0, y0, x1, y1 = box
    width = x1 - x0
    center_x, center_y = x0 + width * 0.5, y0 + (y1 - y0) * 0.5
    radius = width * 0.5
    draw.ellipse(box, outline=color, width=stroke)

    inner = radius * 0.40
    points = [
        (center_x + inner * cos(radians(angle)), center_y + inner * sin(radians(angle)))
        for angle in range(-90, 270, 72)
    ]
    draw.polygon(points, fill=color)
    for point in points[:3]:
        edge_x = center_x + (point[0] - center_x) / inner * radius
        edge_y = center_y + (point[1] - center_y) / inner * radius
        draw.line((point[0], point[1], edge_x, edge_y), fill=color, width=max(stroke - 1, 1))


def _basketball(draw: ImageDraw.ImageDraw, box: Box, color: RGB | RGBA, stroke: int) -> None:
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    thin = max(stroke - 1, 1)
    draw.ellipse(box, outline=color, width=stroke)
    draw.line((x0 + width * 0.5, y0, x0 + width * 0.5, y1), fill=color, width=thin)
    draw.line((x0, y0 + height * 0.5, x1, y0 + height * 0.5), fill=color, width=thin)
    draw.arc((x0 - width * 0.5, y0, x0 + width * 0.5, y1), 300, 60, fill=color, width=thin)
    draw.arc((x0 + width * 0.5, y0, x1 + width * 0.5, y1), 120, 240, fill=color, width=thin)


def _racket(draw: ImageDraw.ImageDraw, box: Box, color: RGB | RGBA, stroke: int) -> None:
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    draw.ellipse(
        (x0 + width * 0.16, y0 + height * 0.04, x1 - width * 0.16, y0 + height * 0.62),
        outline=color,
        width=stroke,
    )
    draw.line((x0 + width * 0.5, y0 + height * 0.62, x0 + width * 0.5, y1 - height * 0.02), fill=color, width=stroke)


def _run(draw: ImageDraw.ImageDraw, box: Box, color: RGB | RGBA, stroke: int) -> None:
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    head = width * 0.13
    head_x, head_y = x0 + width * 0.54, y0 + height * 0.12
    draw.ellipse((head_x - head, head_y - head, head_x + head, head_y + head), fill=color)

    hip = (x0 + width * 0.38, y0 + height * 0.58)
    draw.line((head_x, y0 + height * 0.28, hip[0], hip[1]), fill=color, width=stroke)
    draw.line((hip[0], hip[1], x0 + width * 0.56, y1 - height * 0.06), fill=color, width=stroke)
    draw.line((hip[0], hip[1], x0 + width * 0.14, y1 - height * 0.14), fill=color, width=stroke)
    draw.line((x0 + width * 0.50, y0 + height * 0.36, x1 - width * 0.08, y0 + height * 0.26), fill=color, width=stroke)
    draw.line((x0 + width * 0.46, y0 + height * 0.42, x0 + width * 0.16, y0 + height * 0.46), fill=color, width=stroke)


def _bike(draw: ImageDraw.ImageDraw, box: Box, color: RGB | RGBA, stroke: int) -> None:
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    thin = max(stroke - 1, 1)
    radius = width * 0.23
    axle_y = y1 - radius - height * 0.06
    left_x, right_x = x0 + radius + width * 0.02, x1 - radius - width * 0.02
    for center_x in (left_x, right_x):
        draw.ellipse(
            (center_x - radius, axle_y - radius, center_x + radius, axle_y + radius), outline=color, width=thin
        )

    saddle = (x0 + width * 0.44, y0 + height * 0.30)
    bars = (x1 - width * 0.26, y0 + height * 0.26)
    for start, end in ((left_x, axle_y), (right_x, axle_y)):
        draw.line((start, end, saddle[0], saddle[1]), fill=color, width=thin)
    draw.line((saddle[0], saddle[1], bars[0], bars[1]), fill=color, width=thin)
    draw.line((bars[0], bars[1], right_x, axle_y), fill=color, width=thin)
    draw.line((bars[0] - width * 0.10, bars[1], bars[0] + width * 0.08, bars[1]), fill=color, width=thin)


def _swim(draw: ImageDraw.ImageDraw, box: Box, color: RGB | RGBA, stroke: int) -> None:
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    head = width * 0.12
    head_x, head_y = x0 + width * 0.26, y0 + height * 0.22
    draw.ellipse((head_x - head, head_y - head, head_x + head, head_y + head), fill=color)
    draw.line((head_x + head, y0 + height * 0.34, x1 - width * 0.10, y0 + height * 0.20), fill=color, width=stroke)

    for row in (0.64, 0.86):
        y = y0 + height * row
        draw.arc(
            (x0, y - height * 0.12, x0 + width * 0.5, y + height * 0.12), 0, 180, fill=color, width=max(stroke - 1, 1)
        )
        draw.arc(
            (x0 + width * 0.5, y - height * 0.12, x1, y + height * 0.12), 180, 360, fill=color, width=max(stroke - 1, 1)
        )


def _dumbbell(draw: ImageDraw.ImageDraw, box: Box, color: RGB | RGBA, stroke: int) -> None:
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    draw.line((x0 + width * 0.24, y0 + height * 0.5, x1 - width * 0.24, y0 + height * 0.5), fill=color, width=stroke)
    for x in (x0 + width * 0.16, x1 - width * 0.16):
        draw.line((x, y0 + height * 0.24, x, y1 - height * 0.24), fill=color, width=stroke + 2)


def _yoga(draw: ImageDraw.ImageDraw, box: Box, color: RGB | RGBA, stroke: int) -> None:
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    head = width * 0.12
    center_x = x0 + width * 0.5
    draw.ellipse((center_x - head, y0 + height * 0.14 - head, center_x + head, y0 + height * 0.14 + head), fill=color)
    draw.line((center_x, y0 + height * 0.30, center_x, y0 + height * 0.62), fill=color, width=stroke)
    draw.line((x0 + width * 0.12, y0 + height * 0.44, x1 - width * 0.12, y0 + height * 0.44), fill=color, width=stroke)
    draw.line((center_x, y0 + height * 0.62, x0 + width * 0.16, y1 - height * 0.10), fill=color, width=stroke)
    draw.line((center_x, y0 + height * 0.62, x1 - width * 0.16, y1 - height * 0.10), fill=color, width=stroke)


def _flag(draw: ImageDraw.ImageDraw, box: Box, color: RGB | RGBA, stroke: int) -> None:
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    draw.line((x0 + width * 0.22, y0 + height * 0.04, x0 + width * 0.22, y1 - height * 0.04), fill=color, width=stroke)
    draw.polygon(
        [
            (x0 + width * 0.22, y0 + height * 0.08),
            (x1 - width * 0.06, y0 + height * 0.26),
            (x0 + width * 0.22, y0 + height * 0.48),
        ],
        fill=color,
    )


def _jersey(draw: ImageDraw.ImageDraw, box: Box, color: RGB | RGBA, stroke: int) -> None:
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    draw.polygon(
        [
            (x0 + width * 0.32, y0 + height * 0.12),
            (x0 + width * 0.42, y0 + height * 0.22),
            (x0 + width * 0.58, y0 + height * 0.22),
            (x0 + width * 0.68, y0 + height * 0.12),
            (x1 - width * 0.04, y0 + height * 0.30),
            (x1 - width * 0.18, y0 + height * 0.46),
            (x1 - width * 0.22, y1 - height * 0.08),
            (x0 + width * 0.22, y1 - height * 0.08),
            (x0 + width * 0.18, y0 + height * 0.46),
            (x0 + width * 0.04, y0 + height * 0.30),
        ],
        outline=color,
        width=stroke,
    )


def _tag(draw: ImageDraw.ImageDraw, box: Box, color: RGB | RGBA, stroke: int) -> None:
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    draw.polygon(
        [
            (x0 + width * 0.06, y0 + height * 0.08),
            (x0 + width * 0.54, y0 + height * 0.08),
            (x1 - width * 0.04, y0 + height * 0.54),
            (x0 + width * 0.50, y1 - height * 0.04),
            (x0 + width * 0.06, y0 + height * 0.56),
        ],
        outline=color,
        width=stroke,
    )
    hole = width * 0.07
    hole_x, hole_y = x0 + width * 0.22, y0 + height * 0.26
    draw.ellipse((hole_x - hole, hole_y - hole, hole_x + hole, hole_y + hole), fill=color)


def _bolt(draw: ImageDraw.ImageDraw, box: Box, color: RGB | RGBA, stroke: int) -> None:
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    draw.polygon(
        [
            (x0 + width * 0.60, y0 + height * 0.02),
            (x0 + width * 0.20, y0 + height * 0.56),
            (x0 + width * 0.46, y0 + height * 0.56),
            (x0 + width * 0.38, y1 - height * 0.02),
            (x1 - width * 0.16, y0 + height * 0.42),
            (x0 + width * 0.50, y0 + height * 0.42),
        ],
        fill=color,
    )


def _trophy(draw: ImageDraw.ImageDraw, box: Box, color: RGB | RGBA, stroke: int) -> None:
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    thin = max(stroke - 1, 1)
    cup = (x0 + width * 0.24, y0 + height * 0.10, x1 - width * 0.24, y0 + height * 0.58)
    draw.chord(cup, 0, 180, outline=color, width=stroke)
    draw.line((cup[0], cup[1], cup[2], cup[1]), fill=color, width=stroke)
    draw.arc(
        (x0 + width * 0.04, y0 + height * 0.12, x0 + width * 0.34, y0 + height * 0.46), 90, 270, fill=color, width=thin
    )
    draw.arc(
        (x1 - width * 0.34, y0 + height * 0.12, x1 - width * 0.04, y0 + height * 0.46), 270, 90, fill=color, width=thin
    )
    draw.line((x0 + width * 0.5, y0 + height * 0.58, x0 + width * 0.5, y1 - height * 0.20), fill=color, width=stroke)
    draw.line(
        (x0 + width * 0.28, y1 - height * 0.10, x1 - width * 0.28, y1 - height * 0.10), fill=color, width=stroke + 1
    )


def _star(draw: ImageDraw.ImageDraw, box: Box, color: RGB | RGBA, stroke: int) -> None:
    x0, y0, x1, y1 = box
    width = x1 - x0
    center_x, center_y = x0 + width * 0.5, y0 + (y1 - y0) * 0.5
    outer = width * 0.5
    inner = outer * 0.42

    points = []
    for step in range(10):
        radius = outer if step % 2 == 0 else inner
        angle = radians(-90 + step * 36)
        points.append((center_x + radius * cos(angle), center_y + radius * sin(angle)))
    draw.polygon(points, fill=color)


def _sparkles(draw: ImageDraw.ImageDraw, box: Box, color: RGB | RGBA, stroke: int) -> None:
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    _star(draw, (x0, y0, x0 + width * 0.68, y0 + height * 0.68), color, stroke)
    _star(draw, (x0 + width * 0.56, y0 + height * 0.54, x1, y1), color, stroke)


def _check(draw: ImageDraw.ImageDraw, box: Box, color: RGB | RGBA, stroke: int) -> None:
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    draw.line(
        (x0 + width * 0.16, y0 + height * 0.52, x0 + width * 0.42, y1 - height * 0.22),
        fill=color,
        width=stroke,
    )
    draw.line(
        (x0 + width * 0.42, y1 - height * 0.22, x1 - width * 0.14, y0 + height * 0.22),
        fill=color,
        width=stroke,
    )


def _share(draw: ImageDraw.ImageDraw, box: Box, color: RGB | RGBA, stroke: int) -> None:
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    node = width * 0.14
    points = [
        (x0 + width * 0.18, y0 + height * 0.50),
        (x1 - width * 0.16, y0 + height * 0.16),
        (x1 - width * 0.16, y1 - height * 0.16),
    ]
    for center_x, center_y in points[1:]:
        draw.line((points[0][0], points[0][1], center_x, center_y), fill=color, width=max(stroke - 1, 1))
    for center_x, center_y in points:
        draw.ellipse((center_x - node, center_y - node, center_x + node, center_y + node), outline=color, width=stroke)


def _user_plus(draw: ImageDraw.ImageDraw, box: Box, color: RGB | RGBA, stroke: int) -> None:
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    _user(draw, (x0 - width * 0.08, y0 + height * 0.04, x0 + width * 0.66, y1), color, stroke)

    center_x, center_y = x1 - width * 0.16, y0 + height * 0.28
    arm = width * 0.16
    draw.line((center_x - arm, center_y, center_x + arm, center_y), fill=color, width=stroke)
    draw.line((center_x, center_y - arm, center_x, center_y + arm), fill=color, width=stroke)


def _dot(draw: ImageDraw.ImageDraw, box: Box, color: RGB | RGBA, stroke: int) -> None:
    x0, y0, x1, y1 = box
    inset = (x1 - x0) * 0.28
    draw.ellipse((x0 + inset, y0 + inset, x1 - inset, y1 - inset), fill=color)


def _link(draw: ImageDraw.ImageDraw, box: Box, color: RGB | RGBA, stroke: int) -> None:
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    draw.rounded_rectangle(
        (x0 + width * 0.04, y0 + height * 0.34, x0 + width * 0.58, y1 - height * 0.16),
        radius=max(round(height * 0.16), 2),
        outline=color,
        width=stroke,
    )
    draw.rounded_rectangle(
        (x0 + width * 0.42, y0 + height * 0.16, x1 - width * 0.04, y1 - height * 0.34),
        radius=max(round(height * 0.16), 2),
        outline=color,
        width=stroke,
    )


def _arrows(draw: ImageDraw.ImageDraw, box: Box, color: RGB | RGBA, stroke: int) -> None:
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    center_x = x0 + width * 0.5
    draw.line((center_x, y0 + height * 0.12, center_x, y1 - height * 0.12), fill=color, width=stroke)
    for direction in (1, -1):
        tip_y = y0 + height * 0.04 if direction > 0 else y1 - height * 0.04
        base_y = tip_y + height * 0.24 * direction
        draw.polygon(
            [(center_x, tip_y), (center_x - width * 0.20, base_y), (center_x + width * 0.20, base_y)],
            fill=color,
        )


_ICONS: dict[str, Callable[[ImageDraw.ImageDraw, Box, RGB | RGBA, int], None]] = {
    "arrows": _arrows,
    "ball": _ball,
    "basketball": _basketball,
    "bike": _bike,
    "bolt": _bolt,
    "calendar": _calendar,
    "calendar-x": _calendar_x,
    "check": _check,
    "clock": _clock,
    "dot": _dot,
    "dumbbell": _dumbbell,
    "flag": _flag,
    "globe": _globe,
    "jersey": _jersey,
    "link": _link,
    "lock": _lock,
    "pin": _pin,
    "racket": _racket,
    "run": _run,
    "share": _share,
    "shield": _shield,
    "sparkles": _sparkles,
    "star": _star,
    "swim": _swim,
    "tag": _tag,
    "trophy": _trophy,
    "unlock": _unlock,
    "user": _user,
    "user-plus": _user_plus,
    "users": _users,
    "yoga": _yoga,
}

ICON_NAMES = tuple(sorted(_ICONS))


def badge(
    draw: ImageDraw.ImageDraw,
    box: Box,
    fill: RGB,
    mark: RGB,
    *,
    name: str = "check",
) -> None:
    """Filled disc with an icon on top, used for the verified tick."""
    draw.ellipse(box, fill=with_alpha(fill, 255))

    x0, y0, x1, y1 = box
    inset = (x1 - x0) * 0.24
    draw_icon(draw, name, (x0 + inset, y0 + inset, x1 - inset, y1 - inset), mark)
