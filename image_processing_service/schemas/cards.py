"""Wire contract between playbook-be and the share card renderer.

playbook-be speaks camelCase JSON, so every model is parsed by alias and dumped
by alias. Unknown fields are ignored on the way in: the backend can add keys
without a lockstep deploy of this service.
"""

from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

CardKind = Literal["USER", "SQUAD", "EVENT"]
CardLayout = Literal["POSTER", "CARD", "STORY"]
ImageFormat = Literal["AUTO", "PNG", "JPEG", "WEBP"]
RenderStatus = Literal["COMPLETED", "FAILED", "REJECTED"]

ErrorCode = Literal[
    "INVALID_REQUEST",
    "OVERLOADED",
    "TIMEOUT",
    "SOURCE_IMAGE_FAILED",
    "IMAGE_TOO_LARGE",
    "RENDER_FAILED",
]

# Rendered pixel dimensions per layout. POSTER is the 4:5 feed post, STORY the
# 9:16 full screen story, CARD the 1.91:1 link preview / Open Graph size.
LAYOUT_SIZES: dict[str, tuple[int, int]] = {
    "POSTER": (1080, 1350),
    "STORY": (1080, 1920),
    "CARD": (1200, 630),
}

# Hard ceiling on any inbound string, applied before the renderer sees it.
MAX_TEXT_LENGTH = 2000

# One 8 MB binary image is roughly 10.7 MB as base64. Limit the aggregate
# inline payload as well as the HTTP body; remote URLs are preferred when a
# card carries several photos.
MAX_INLINE_IMAGE_CHARS = 10_800_000

# The discriminator and the (potentially large) inline images are left alone.
_UNCLIPPED_FIELDS = {
    "kind",
    "avatarBase64",
    "avatar_base64",
    "coverBase64",
    "cover_base64",
    "memberAvatarsBase64",
    "member_avatars_base64",
}


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")


class Stat(CamelModel):
    """One number in the stat strip, e.g. label="Matches" value="128".

    `icon` names a pictogram from `render.icons`; when it is absent one is
    inferred from the label, so the backend does not have to know the icon set.
    """

    label: str
    value: str
    icon: str | None = None


class BaseCard(CamelModel):
    """Fields every card kind shares."""

    title: str
    subtitle: str | None = None
    description: str | None = None
    location: str | None = None

    # Deep link printed in the footer and encoded into the QR code.
    share_url: str | None = None

    # Imagery. Prefer the inline base64 variants: they avoid a network hop on
    # the render path and keep this service from fetching arbitrary URLs.
    avatar_base64: str | None = None
    avatar_url: str | None = None
    cover_base64: str | None = None
    cover_url: str | None = None

    stats: list[Stat] = Field(default_factory=list, max_length=4)
    badges: list[str] = Field(default_factory=list, max_length=4)

    # Optional "#RRGGBB" override for the theme accent, e.g. a squad's colour.
    accent_color: str | None = None
    footer_note: str | None = None

    # Overrides for the call to action above the QR code and the muted row of
    # affordances under it. Both have per kind defaults.
    cta_label: str | None = None
    actions: list[str] = Field(default_factory=list, max_length=3)

    @model_validator(mode="before")
    @classmethod
    def clip_long_strings(cls, data: Any) -> Any:
        """A 40 kB bio should not become a 40 kB word wrap. Clip on the way in
        rather than rejecting the request."""
        if not isinstance(data, dict):
            return data

        clipped: dict[str, Any] = {}
        for key, value in data.items():
            if key in _UNCLIPPED_FIELDS:
                clipped[key] = value
            elif isinstance(value, str):
                clipped[key] = value[:MAX_TEXT_LENGTH]
            elif isinstance(value, list):
                clipped[key] = [item[:MAX_TEXT_LENGTH] if isinstance(item, str) else item for item in value]
            else:
                clipped[key] = value
        return clipped

    @model_validator(mode="after")
    def limit_inline_images(self) -> "BaseCard":
        inline = [self.avatar_base64, self.cover_base64]
        member_images = getattr(self, "member_avatars_base64", [])
        total = sum(len(value) for value in [*inline, *member_images] if value)
        if total > MAX_INLINE_IMAGE_CHARS:
            raise ValueError(f"Inline images exceed {MAX_INLINE_IMAGE_CHARS} base64 characters")
        return self


class UserCard(BaseCard):
    kind: Literal["USER"] = "USER"

    handle: str | None = None
    level: int | None = None
    sports: list[str] = Field(default_factory=list, max_length=6)

    # Tick next to the display name, and the small green "Active player" line.
    verified: bool = False
    status_label: str | None = None


class SquadCard(BaseCard):
    kind: Literal["SQUAD"] = "SQUAD"

    sport: str | None = None
    member_count: int | None = None
    privacy: str | None = None
    language: str | None = None
    founded_year: int | None = None
    captain_name: str | None = None

    # Faces for the "+N" stack in the detail strip. Same rules as `avatarBase64`:
    # inline data preferred, remote URLs only from allow listed hosts.
    member_avatars_base64: list[str] = Field(default_factory=list, max_length=4)
    member_avatar_urls: list[str] = Field(default_factory=list, max_length=4)


class EventCard(BaseCard):
    kind: Literal["EVENT"] = "EVENT"

    sport: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    venue: str | None = None
    host_name: str | None = None
    squad_name: str | None = None
    spots_left: int | None = None
    price_label: str | None = None

    # "5v5", "Open to all" - the two lines of the detail panel that come from
    # how the event is set up rather than from a number.
    format_label: str | None = None
    audience_label: str | None = None


CardPayload = Annotated[UserCard | SquadCard | EventCard, Field(discriminator="kind")]


class RenderRequest(CamelModel):
    """A single share card to draw.

    `kind` lives at the top level for the backend's convenience and is copied
    into the payload so pydantic can pick the right payload model.
    """

    request_id: str = Field(default_factory=lambda: str(uuid4()))
    kind: CardKind
    payload: CardPayload

    layout: CardLayout = "POSTER"
    format: ImageFormat = "AUTO"
    theme: str | None = None
    locale: str | None = None

    # Lets the backend route results to a per-environment topic. When unset the
    # bridge replies on the configured default result topic.
    reply_topic: str | None = None
    requested_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def apply_kind_to_payload(cls, data: Any) -> Any:
        if isinstance(data, dict):
            kind = data.get("kind")
            payload = data.get("payload")
            if isinstance(kind, str) and isinstance(payload, dict) and "kind" not in payload:
                data = {**data, "payload": {**payload, "kind": kind.upper()}}
        return data

    @field_validator("kind", "layout", "format", mode="before")
    @classmethod
    def normalise_enums(cls, value: Any) -> Any:
        return value.upper() if isinstance(value, str) else value

    @property
    def size(self) -> tuple[int, int]:
        return LAYOUT_SIZES[self.layout]


class RenderError(CamelModel):
    code: ErrorCode
    message: str


class RenderResult(CamelModel):
    """What the backend gets back, one per request, keyed by `requestId`."""

    request_id: str
    status: RenderStatus
    kind: CardKind | None = None
    layout: CardLayout | None = None

    # Present when status == COMPLETED. Raw base64, no data URI prefix: the
    # frontend builds `data:{contentType};base64,{imageBase64}`.
    image_base64: str | None = None
    content_type: str | None = None
    width: int | None = None
    height: int | None = None
    byte_size: int | None = None

    render_ms: int | None = None
    queued_ms: int | None = None
    error: RenderError | None = None
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def failure(
        cls,
        request_id: str,
        code: ErrorCode,
        message: str,
        *,
        status: RenderStatus = "FAILED",
        kind: CardKind | None = None,
        layout: CardLayout | None = None,
    ) -> "RenderResult":
        return cls(
            request_id=request_id,
            status=status,
            kind=kind,
            layout=layout,
            error=RenderError(code=code, message=message),
        )
