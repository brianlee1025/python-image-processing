from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings

ImageFormatName = Literal["png", "jpeg", "webp"]


class RenderSettings(BaseSettings):
    """Share card rendering and worker pool configuration.

    Every field is settable through an environment variable of the same name in
    upper case, e.g. ``RENDER_WORKERS=8``. List fields are parsed as JSON, e.g.
    ``RENDER_REMOTE_IMAGE_HOSTS='["cdn.playbookapp.org"]'``.
    """

    # Worker pool. The pool admits at most `render_workers + render_queue_size`
    # jobs; anything beyond that is rejected so a burst of users cannot pile up
    # unbounded work in memory.
    render_workers: int = Field(default=4, ge=1, le=64)
    render_queue_size: int = Field(default=32, ge=0, le=1000)

    # How long a single card may take before the worker gives up.
    render_timeout_seconds: float = Field(default=20.0, gt=0, le=300)

    # How long an HTTP caller waits for a slot before receiving a 503.
    render_admission_wait_seconds: float = Field(default=5.0, ge=0, le=60)

    # Output. `render_max_bytes` is the ceiling for the *encoded* image, chosen
    # to leave room for base64 inflation (~4/3) inside a 1 MiB Kafka message.
    render_default_format: ImageFormatName = "png"
    render_max_bytes: int = Field(default=600_000, ge=10_000, le=20_000_000)
    render_jpeg_quality: int = Field(default=88, ge=1, le=95)
    render_webp_quality: int = Field(default=86, ge=1, le=95)

    # Optional TrueType fonts. When unset the renderer falls back to bundled
    # fonts in `image_processing_service/static/fonts`, then to system fonts,
    # then to Pillow's built in font.
    render_font_regular: Path | None = None
    render_font_bold: Path | None = None

    # Incoming avatars/covers. Remote fetching is off by default: the payload
    # should carry `avatarBase64`. When enabled, only the listed hosts are
    # allowed, which keeps this service from being an SSRF proxy.
    render_allow_remote_images: bool = False
    render_remote_image_hosts: list[str] = []
    render_allow_private_remote_hosts: bool = False
    render_remote_require_https: bool = True
    render_remote_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    render_max_source_bytes: int = Field(default=8_000_000, ge=1024, le=50_000_000)
    render_max_source_pixels: int = Field(default=30_000_000, ge=10_000, le=100_000_000)

    # Squads and events without a banner get generated cover art. Point this
    # at a directory of photographs to use those instead; files are matched by
    # kind and sport, e.g. `squad-football.jpg`, `event.jpg`, `cover.jpg`.
    render_default_cover_dir: Path | None = None

    # Imagery is decoration: by default a photo that will not load costs the
    # user their avatar, not their card, and the reason is logged. Turn this on
    # to fail the request instead, e.g. while debugging a storage change.
    render_strict_images: bool = False

    # Branding used in the card footer.
    render_brand_name: str = "Playbook"
    render_brand_url: str = "playbookapp.org"
