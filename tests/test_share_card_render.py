"""Tests for the Pillow renderer."""

import base64
import socket
from io import BytesIO
from urllib.error import HTTPError

import pytest
from PIL import Image

from image_processing_service.render import media
from image_processing_service.render.encode import encode
from image_processing_service.render.media import SourceImageError, load_source
from image_processing_service.samples import sample_request
from image_processing_service.schemas.cards import RenderRequest
from image_processing_service.services.share_cards import render_now
from image_processing_service.settings import settings


def photo_base64(size=(400, 400), image_format="PNG") -> str:
    image = Image.new("RGB", size, (120, 90, 60))
    buffer = BytesIO()
    image.save(buffer, format=image_format)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def decoded(result) -> Image.Image:
    assert result.image_base64 is not None
    return Image.open(BytesIO(base64.b64decode(result.image_base64)))


@pytest.mark.parametrize("kind", ["USER", "SQUAD", "EVENT", "POST"])
def test_every_card_kind_renders(kind):
    result = render_now(sample_request(kind=kind))

    assert result.status == "COMPLETED", result.error
    assert result.content_type == "image/png"
    assert (result.width, result.height) == (1080, 1350)
    assert decoded(result).size == (1080, 1350)


@pytest.mark.parametrize(
    ("layout", "size"),
    [("POSTER", (1080, 1350)), ("STORY", (1080, 1920)), ("CARD", (1200, 630))],
)
def test_layouts_have_the_documented_dimensions(layout, size):
    result = render_now(sample_request(kind="EVENT", layout=layout))

    assert result.status == "COMPLETED", result.error
    assert decoded(result).size == size


def test_renders_a_card_that_only_has_a_title():
    request = RenderRequest.model_validate({"kind": "SQUAD", "payload": {"title": "Ballers"}})
    result = render_now(request)

    assert result.status == "COMPLETED", result.error


def test_uses_the_supplied_avatar_and_cover():
    request = RenderRequest.model_validate(
        {
            "kind": "USER",
            "payload": {
                "title": "Aisyah Rahman",
                "avatarBase64": photo_base64(),
                "coverBase64": photo_base64((900, 600), "JPEG"),
            },
        }
    )
    result = render_now(request)

    assert result.status == "COMPLETED", result.error


def test_data_uri_prefixes_are_accepted():
    payload = f"data:image/png;base64,{photo_base64()}"

    assert load_source(base64_data=payload) is not None


def test_unusable_imagery_costs_the_avatar_not_the_card():
    """A card the user can still share beats an error they cannot."""
    request = RenderRequest.model_validate(
        {"requestId": "bad-image", "kind": "USER", "payload": {"title": "Aisyah", "avatarBase64": "not-an-image"}}
    )
    result = render_now(request)

    assert result.status == "COMPLETED", result.error
    assert result.request_id == "bad-image"


def test_strict_mode_turns_unusable_imagery_into_a_failure(monkeypatch):
    monkeypatch.setattr(settings, "render_strict_images", True)
    request = RenderRequest.model_validate(
        {"requestId": "bad-image", "kind": "USER", "payload": {"title": "Aisyah", "avatarBase64": "not-an-image"}}
    )

    result = render_now(request)

    assert result.status == "FAILED"
    assert result.error is not None
    assert result.error.code == "SOURCE_IMAGE_FAILED"


def test_a_remote_avatar_that_is_not_allow_listed_is_dropped():
    """What playbook-be's presigned URLs hit when the allow list is unset."""
    request = RenderRequest.model_validate(
        {
            "kind": "USER",
            "payload": {"title": "Aisyah", "avatarUrl": "https://minio.example.test/avatars/1.png"},
        }
    )

    assert render_now(request).status == "COMPLETED"


def test_remote_images_are_refused_when_not_enabled(monkeypatch):
    """Set explicitly rather than relying on the ambient config: a developer's
    .env turns remote fetching on for the local backend."""
    monkeypatch.setattr(settings, "render_allow_remote_images", False)

    with pytest.raises(SourceImageError):
        load_source(url="https://example.test/avatar.png")


def test_remote_images_are_refused_from_hosts_outside_the_allow_list(monkeypatch):
    monkeypatch.setattr(settings, "render_allow_remote_images", True)
    monkeypatch.setattr(settings, "render_remote_image_hosts", ["cdn.playbookapp.org"])

    with pytest.raises(SourceImageError, match="allow listed"):
        load_source(url="https://attacker.test/avatar.png")


def test_remote_images_are_refused_when_dns_resolves_privately(monkeypatch):
    monkeypatch.setattr(settings, "render_allow_remote_images", True)
    monkeypatch.setattr(settings, "render_remote_image_hosts", ["cdn.playbookapp.org"])
    monkeypatch.setattr(settings, "render_allow_private_remote_hosts", False)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
    )

    with pytest.raises(SourceImageError, match="non-public"):
        load_source(url="https://cdn.playbookapp.org/avatar.png")


def test_remote_redirects_are_not_followed(monkeypatch):
    monkeypatch.setattr(settings, "render_allow_remote_images", True)
    monkeypatch.setattr(settings, "render_remote_image_hosts", ["cdn.playbookapp.org"])
    monkeypatch.setattr(settings, "render_allow_private_remote_hosts", False)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )

    def redirect(*args, **kwargs):
        raise HTTPError("https://cdn.playbookapp.org/avatar.png", 302, "Found", {}, None)

    monkeypatch.setattr(media._OPENER, "open", redirect)

    with pytest.raises(SourceImageError, match="HTTP 302"):
        load_source(url="https://cdn.playbookapp.org/avatar.png")


def test_source_pixel_limit_is_a_hard_rejection(monkeypatch):
    monkeypatch.setattr(settings, "render_max_source_pixels", 100)

    with pytest.raises(SourceImageError, match="pixels"):
        load_source(base64_data=photo_base64((11, 10)))


def test_theme_and_accent_overrides_render():
    request = RenderRequest.model_validate(
        {"kind": "SQUAD", "theme": "ocean", "payload": {"title": "Ballers", "accentColor": "#ff0066"}}
    )

    assert render_now(request).status == "COMPLETED"


def test_unknown_theme_falls_back_instead_of_failing():
    request = RenderRequest.model_validate({"kind": "USER", "theme": "neon-disco", "payload": {"title": "Aisyah"}})

    assert render_now(request).status == "COMPLETED"


def test_encoding_drops_to_a_lossy_format_to_meet_the_budget():
    """A PNG poster does not fit in a small Kafka message, so the encoder is
    expected to trade format and then size for bytes."""
    image = Image.open(BytesIO(base64.b64decode(render_now(sample_request()).image_base64 or "")))

    encoded = encode(image, "PNG", max_bytes=40_000)

    assert encoded.byte_size <= 40_000
    assert encoded.content_type in {"image/webp", "image/jpeg"}


def test_encoding_keeps_png_when_it_fits():
    image = Image.new("RGB", (600, 600), (10, 20, 30))
    encoded = encode(image, "PNG", max_bytes=500_000)

    assert encoded.content_type == "image/png"
    assert encoded.width == 600


def test_result_carries_timing_and_size():
    result = render_now(sample_request())

    assert result.render_ms is not None and result.render_ms >= 0
    assert result.byte_size is not None and result.byte_size > 0
    assert result.queued_ms is not None
