"""Decoding of the avatar/cover imagery that arrives with a request."""

import base64
import binascii
import ipaddress
import socket
import warnings
from io import BytesIO
from logging import getLogger
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from PIL import Image, ImageOps, UnidentifiedImageError

from ..settings import settings

logger = getLogger(__name__)

# Refuse decompression bombs rather than letting one request eat the box.
Image.MAX_IMAGE_PIXELS = settings.render_max_source_pixels


class SourceImageError(Exception):
    """The caller supplied imagery we could not use."""


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


_OPENER = build_opener(_NoRedirectHandler())


def load_source(base64_data: str | None = None, url: str | None = None) -> Image.Image | None:
    """Inline base64 first, then a URL if remote fetching is enabled.

    Returns None when neither is supplied; the card layouts fall back to
    generated initials or a plain gradient.
    """
    if base64_data:
        return _open(_decode_base64(base64_data))
    if url:
        return _open(_fetch(url))
    return None


def _decode_base64(value: str) -> bytes:
    payload = value.strip()
    if payload.startswith("data:"):
        _, _, payload = payload.partition(",")

    try:
        data = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as error:
        raise SourceImageError("Image is not valid base64") from error

    if not data:
        raise SourceImageError("Image is empty")
    if len(data) > settings.render_max_source_bytes:
        raise SourceImageError(f"Image exceeds {settings.render_max_source_bytes} bytes")
    return data


def _fetch(url: str) -> bytes:
    if not settings.render_allow_remote_images:
        raise SourceImageError("Remote image fetching is disabled, send the image as base64")

    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").rstrip(".").lower()
    allowed_hosts = {host.rstrip(".").lower() for host in settings.render_remote_image_hosts}

    if scheme not in {"http", "https"}:
        raise SourceImageError(f"Unsupported image URL scheme: {parsed.scheme or 'none'}")
    if settings.render_remote_require_https and scheme != "https":
        raise SourceImageError("Remote image URL must use HTTPS")
    if parsed.username or parsed.password:
        raise SourceImageError("Remote image URL must not contain credentials")
    if not hostname or hostname not in allowed_hosts:
        raise SourceImageError(f"Image host is not allow listed: {hostname or 'none'}")

    _validate_resolved_host(hostname, parsed.port)

    # Redirects are disabled: every network destination must be the exact host
    # that was validated above.
    request = Request(url, headers={"User-Agent": settings.project_name})
    try:
        with _OPENER.open(request, timeout=settings.render_remote_timeout_seconds) as response:
            declared_size = response.headers.get("Content-Length")
            if declared_size and int(declared_size) > settings.render_max_source_bytes:
                raise SourceImageError(f"Image exceeds {settings.render_max_source_bytes} bytes")
            data: bytes = response.read(settings.render_max_source_bytes + 1)
    except HTTPError as error:
        raise SourceImageError(f"Remote image server returned HTTP {error.code}") from error
    except (OSError, URLError, ValueError) as error:
        raise SourceImageError("Could not fetch remote image") from error

    if len(data) > settings.render_max_source_bytes:
        raise SourceImageError(f"Image exceeds {settings.render_max_source_bytes} bytes")
    return data


def _open(data: bytes) -> Image.Image:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                if image.width * image.height > settings.render_max_source_pixels:
                    raise SourceImageError(f"Image exceeds {settings.render_max_source_pixels} pixels")
                image.load()
                rotated = ImageOps.exif_transpose(image)
                return (rotated or image).convert("RGB")
    except SourceImageError:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise SourceImageError(f"Could not decode image: {error}") from error


def _validate_resolved_host(hostname: str, port: int | None) -> None:
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, port or 443, type=socket.SOCK_STREAM)}
    except OSError as error:
        raise SourceImageError("Could not resolve image host") from error

    if not addresses:
        raise SourceImageError("Could not resolve image host")
    if settings.render_allow_private_remote_hosts:
        return

    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise SourceImageError("Image host resolves to a non-public address")
