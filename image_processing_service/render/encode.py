"""Encoding a finished card into bytes that fit inside a Kafka message.

A 1080x1350 PNG is often 1-2 MB, and base64 adds another third on top, which
puts it over the broker's default 1 MiB limit. So instead of trusting one
encoder we try progressively cheaper options until the result fits the budget.
"""

from dataclasses import dataclass
from io import BytesIO
from logging import getLogger

from PIL import Image

from ..settings import settings

logger = getLogger(__name__)

CONTENT_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


@dataclass(frozen=True)
class EncodedImage:
    data: bytes
    content_type: str
    image_format: str
    width: int
    height: int

    @property
    def byte_size(self) -> int:
        return len(self.data)


def encode(image: Image.Image, image_format: str = "AUTO", max_bytes: int | None = None) -> EncodedImage:
    """Encode `image`, shrinking quality then dimensions until it fits.

    `image_format` is the requested format; AUTO starts from the configured
    default. The last attempt always fits in practice, but if it somehow does
    not we return the smallest candidate and log it rather than failing the
    request.
    """
    budget = max_bytes or settings.render_max_bytes
    attempts = _attempts(image_format)
    smallest: EncodedImage | None = None

    # The ladder has to bottom out well under any budget an operator is
    # likely to set: a card that never fits is a card Kafka rejects.
    for scale in (1.0, 0.85, 0.7, 0.55, 0.45):
        candidate_image = image if scale == 1.0 else _scaled(image, scale)

        for fmt, quality in attempts:
            encoded = _save(candidate_image, fmt, quality)
            if encoded.byte_size <= budget:
                if scale != 1.0 or fmt != attempts[0][0]:
                    logger.info(
                        "Encoded card as %s q%s at %.0f%% scale to fit %d bytes",
                        fmt,
                        quality,
                        scale * 100,
                        budget,
                    )
                return encoded
            if smallest is None or encoded.byte_size < smallest.byte_size:
                smallest = encoded

    assert smallest is not None
    logger.warning("Card is %d bytes, over the %d byte budget", smallest.byte_size, budget)
    return smallest


def _attempts(image_format: str) -> list[tuple[str, int]]:
    """Ordered (format, quality) candidates, best looking first."""
    requested = (image_format or "AUTO").upper()
    if requested == "AUTO":
        requested = settings.render_default_format.upper()

    lossy = [
        ("WEBP", settings.render_webp_quality),
        ("JPEG", settings.render_jpeg_quality),
        ("JPEG", 78),
        ("JPEG", 68),
    ]

    if requested == "PNG":
        return [("PNG", 0), *lossy]
    if requested == "WEBP":
        return [("WEBP", settings.render_webp_quality), ("WEBP", 74), ("JPEG", 78), ("JPEG", 68)]
    return [("JPEG", settings.render_jpeg_quality), ("JPEG", 78), ("JPEG", 68)]


def _save(image: Image.Image, image_format: str, quality: int) -> EncodedImage:
    buffer = BytesIO()

    if image_format == "PNG":
        image.save(buffer, format="PNG", optimize=True)
    elif image_format == "WEBP":
        image.save(buffer, format="WEBP", quality=quality, method=4)
    else:
        image.convert("RGB").save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)

    return EncodedImage(
        data=buffer.getvalue(),
        content_type=CONTENT_TYPES[image_format],
        image_format=image_format,
        width=image.width,
        height=image.height,
    )


def _scaled(image: Image.Image, scale: float) -> Image.Image:
    size = (max(round(image.width * scale), 1), max(round(image.height * scale), 1))
    return image.resize(size, Image.Resampling.LANCZOS)
