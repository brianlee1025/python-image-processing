"""The render path everything else calls into.

Both entry points - the Kafka bridge and the HTTP API - hand requests to the
same process wide pool, so a box is never running more renders than it has
worker threads for, no matter which door the work came through.
"""

import base64
import time
from concurrent.futures import Future
from logging import getLogger
from threading import Lock

from PIL import Image

from ..render import SourceImageError, encode, render_card
from ..schemas.cards import RenderRequest, RenderResult
from ..settings import settings
from .pool import PoolFull, RenderPool

logger = getLogger(__name__)

_pool: RenderPool | None = None
_pool_lock = Lock()


def get_render_pool() -> RenderPool:
    """Process wide pool, created on first use."""
    global _pool

    with _pool_lock:
        if _pool is None:
            _pool = RenderPool(workers=settings.render_workers, queue_size=settings.render_queue_size)
            logger.info(
                "Render pool started with %d workers and room for %d queued jobs",
                _pool.workers,
                _pool.capacity - _pool.workers,
            )
        return _pool


def shutdown_render_pool(wait: bool = True) -> None:
    global _pool

    with _pool_lock:
        if _pool is not None:
            _pool.shutdown(wait=wait)
            _pool = None


def submit_render(request: RenderRequest, wait: float = 0.0, pool: RenderPool | None = None) -> "Future[RenderResult]":
    """Queue a render. Raises `PoolFull` when the service is saturated.

    `pool` exists so the Kafka bridge can own its own pool - the pool it checks
    for capacity has to be the pool the work actually lands in.
    """
    return (pool or get_render_pool()).submit(_run, request, time.perf_counter(), wait=wait)


def render_now(request: RenderRequest) -> RenderResult:
    """Render on the calling thread. Used by the CLI and by tests; the serving
    paths go through `submit_render` so they stay bounded."""
    return _run(request, time.perf_counter())


def overloaded_result(request_id: str, message: str = "Render queue is full") -> RenderResult:
    return RenderResult.failure(request_id, "OVERLOADED", message, status="REJECTED")


def _run(request: RenderRequest, queued_at: float) -> RenderResult:
    """Render one card. Never raises: failures come back as a FAILED result so
    the waiting user gets an answer instead of a hung request."""
    queued_ms = int((time.perf_counter() - queued_at) * 1000)
    started = time.perf_counter()

    try:
        image: Image.Image = render_card(request)
        encoded = encode(image, request.format)
    except SourceImageError as error:
        logger.warning("Request %s supplied unusable imagery: %s", request.request_id, error)
        return _with_timing(
            RenderResult.failure(
                request.request_id, "SOURCE_IMAGE_FAILED", "Source image could not be used", kind=request.kind
            ),
            queued_ms,
            started,
        )
    except Exception:
        # One bad card must not take the worker thread with it.
        logger.exception("Render failed for request %s", request.request_id)
        return _with_timing(
            RenderResult.failure(request.request_id, "RENDER_FAILED", "Card rendering failed", kind=request.kind),
            queued_ms,
            started,
        )

    render_ms = int((time.perf_counter() - started) * 1000)
    if render_ms > settings.render_timeout_seconds * 1000:
        logger.warning(
            "Request %s took %dms, over the %.0fs budget",
            request.request_id,
            render_ms,
            settings.render_timeout_seconds,
        )

    return RenderResult(
        request_id=request.request_id,
        status="COMPLETED",
        kind=request.kind,
        layout=request.layout,
        image_base64=base64.b64encode(encoded.data).decode("ascii"),
        content_type=encoded.content_type,
        width=encoded.width,
        height=encoded.height,
        byte_size=encoded.byte_size,
        render_ms=render_ms,
        queued_ms=queued_ms,
    )


def _with_timing(result: RenderResult, queued_ms: int, started: float) -> RenderResult:
    result.queued_ms = queued_ms
    result.render_ms = int((time.perf_counter() - started) * 1000)
    return result


__all__ = [
    "PoolFull",
    "get_render_pool",
    "overloaded_result",
    "render_now",
    "shutdown_render_pool",
    "submit_render",
]
