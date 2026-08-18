"""HTTP twin of the Kafka contract.

Same request body, same result body, same bounded pool. It exists so the card
design can be iterated on in a browser, so the backend has a fallback if the
Kafka path is down, and so load can be checked without a broker.
"""

import asyncio
import base64
import secrets
from concurrent.futures import Future
from logging import getLogger
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from fastapi.responses import JSONResponse

from ..samples import sample_request
from ..schemas.cards import CardKind, CardLayout, RenderRequest, RenderResult
from ..services.pool import PoolFull
from ..services.share_cards import get_render_pool, overloaded_result, submit_render
from ..settings import settings

logger = getLogger(__name__)

router = APIRouter(prefix="/share-cards", tags=["share-cards"])


def require_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    """Close the HTTP renderer by default in production.

    Development remains convenient when no key is configured. A production
    process without a key is treated as misconfigured instead of becoming an
    anonymous CPU service.
    """
    configured = settings.http_api_key
    if configured is None and not settings.is_production:
        return
    if configured is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "HTTP renderer authentication is not configured")
    if x_api_key is None or not secrets.compare_digest(x_api_key, configured.get_secret_value()):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid API key",
            headers={"WWW-Authenticate": "API-Key"},
        )


def require_diagnostics() -> None:
    if settings.is_production:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


@router.get(
    "/pool",
    summary="Render pool saturation",
    dependencies=[Depends(require_api_key), Depends(require_diagnostics)],
)
async def pool_stats() -> dict[str, int]:
    return get_render_pool().stats()


@router.post(
    "/render",
    response_model=RenderResult,
    summary="Render a card and return it as base64",
    dependencies=[Depends(require_api_key)],
)
async def render(request: RenderRequest) -> Response:
    result = await _render(request)

    if result.status == "REJECTED":
        return JSONResponse(
            status_code=503,
            content=result.model_dump(mode="json", by_alias=True),
            headers={"Retry-After": "2"},
        )
    if result.status == "FAILED":
        code = 504 if result.error and result.error.code == "TIMEOUT" else 422
        return JSONResponse(status_code=code, content=result.model_dump(mode="json", by_alias=True))

    return JSONResponse(content=result.model_dump(mode="json", by_alias=True))


@router.post("/preview", summary="Render a card and return the raw image", dependencies=[Depends(require_api_key)])
async def preview(request: RenderRequest) -> Response:
    return _as_image(await _render(request))


@router.get(
    "/sample/{kind}",
    summary="Render a demo card, handy for design work",
    dependencies=[Depends(require_api_key), Depends(require_diagnostics)],
)
async def sample(kind: CardKind = "USER", layout: CardLayout = "POSTER", theme: str | None = None) -> Response:
    request = sample_request(kind=kind.upper(), layout=layout.upper(), theme=theme)  # type: ignore[arg-type]
    return _as_image(await _render(request))


async def _render(request: RenderRequest) -> RenderResult:
    """Queue the card and wait for it, the same way the frontend waits."""
    try:
        future: Future[RenderResult] = submit_render(request, wait=settings.render_admission_wait_seconds)
    except PoolFull:
        logger.warning("Rejected request %s, pool saturated: %s", request.request_id, get_render_pool().stats())
        return overloaded_result(request.request_id)

    try:
        return await asyncio.wait_for(asyncio.wrap_future(future), timeout=settings.render_timeout_seconds)
    except (asyncio.TimeoutError, TimeoutError):
        # A queued job can be cancelled and releases its pool slot. Pillow work
        # already running in a thread cannot be interrupted safely, so that
        # case finishes in the background and is still bounded by the pool.
        cancelled = future.cancel()
        logger.error(
            "Request %s exceeded %.1fs (queued job cancelled: %s)",
            request.request_id,
            settings.render_timeout_seconds,
            cancelled,
        )
        return RenderResult.failure(
            request.request_id,
            "TIMEOUT",
            f"Rendering took longer than {settings.render_timeout_seconds:.0f}s",
            kind=request.kind,
        )


def _as_image(result: RenderResult) -> Response:
    if result.status != "COMPLETED" or not result.image_base64:
        status_code = 503 if result.status == "REJECTED" else 422
        return JSONResponse(status_code=status_code, content=result.model_dump(mode="json", by_alias=True))

    return Response(
        content=base64.b64decode(result.image_base64),
        media_type=result.content_type or "image/png",
        headers={"Cache-Control": "no-store"},
    )
