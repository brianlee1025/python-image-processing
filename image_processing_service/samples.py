"""Demo payloads used by the CLI, the preview endpoints and the tests.

They double as living documentation of what playbook-be should send: every
field a card draws appears here at least once.
"""

from datetime import datetime, timedelta, timezone

from .schemas.cards import CardKind, CardLayout, EventCard, PostCard, RenderRequest, SquadCard, Stat, UserCard

SAMPLE_USER = UserCard(
    title="Aisyah Rahman",
    subtitle="@aisyahplays",
    description="Weekend striker, weekday physio. Always up for a 7-a-side if the pitch is dry.",
    location="Kuala Lumpur, MY",
    share_url="https://playbookapp.org/u/v83bYqnxOH",
    handle="@aisyahplays",
    level=12,
    verified=True,
    status_label="Active player",
    sports=["Football", "Futsal", "Running"],
    badges=["MVP x4", "100 Games"],
    stats=[
        Stat(label="Squads", value="6"),
        Stat(label="Events", value="48"),
        Stat(label="Connections", value="132"),
        Stat(label="Joined", value="2024"),
    ],
)

SAMPLE_SQUAD = SquadCard(
    title="Bukit Jalil Ballers",
    subtitle="Sport is better with your people.",
    description="Casual 7-a-side crew that has been running since 2019. Newcomers welcome, boots not optional.",
    location="Bukit Jalil, Kuala Lumpur",
    share_url="https://playbookapp.org/s/zb9l8qk",
    sport="Football",
    privacy="Open squad",
    language="English",
    founded_year=2019,
    captain_name="Aisyah Rahman",
    member_count=48,
    badges=["Top 10 squad"],
    stats=[
        Stat(label="Members", value="48"),
        Stat(label="Founded", value="2019"),
    ],
)

SAMPLE_EVENT = EventCard(
    title="Friday Night Futsal",
    subtitle="Bukit Jalil Ballers",
    description="Two courts booked, bibs provided. Come early for the warm up, stay late for the mamak.",
    location="Kuala Lumpur",
    share_url="https://playbookapp.org/e/h1cj5p33",
    sport="Futsal",
    starts_at=datetime.now(timezone.utc) + timedelta(days=3, hours=5),
    ends_at=datetime.now(timezone.utc) + timedelta(days=3, hours=7),
    venue="Court 2, Sports Arena Bukit Jalil",
    host_name="Aisyah Rahman",
    squad_name="Bukit Jalil Ballers",
    format_label="5v5",
    audience_label="Open to all",
    spots_left=3,
    price_label="RM 15",
    stats=[
        Stat(label="Going", value="17"),
        Stat(label="Spots", value="3"),
        Stat(label="Duration", value="2h"),
        Stat(label="Price", value="RM 15"),
    ],
)

SAMPLE_POST = PostCard(
    title="Aisyah Rahman",
    description=(
        "New post features are live! Playbook posts now automatically highlight "
        "dates, fees and squad tags, so a caption like 'Join us on 01/09/2026 - "
        "entry fee is RM25' reads clearly at a glance."
    ),
    share_url="https://playbookapp.org/p/qm4dz1x",
    handle="@aisyahplays",
    verified=True,
    level=12,
    posted_at=datetime.now(timezone.utc) - timedelta(hours=2),
    squad_name="Bukit Jalil Ballers",
    stats=[
        Stat(label="Likes", value="128"),
        Stat(label="Comments", value="24"),
    ],
)

SAMPLES = {"USER": SAMPLE_USER, "SQUAD": SAMPLE_SQUAD, "EVENT": SAMPLE_EVENT, "POST": SAMPLE_POST}


def sample_request(kind: CardKind = "USER", layout: CardLayout = "POSTER", theme: str | None = None) -> RenderRequest:
    payload = SAMPLES[kind]
    return RenderRequest(kind=kind, payload=payload.model_copy(deep=True), layout=layout, theme=theme)
