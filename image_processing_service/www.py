import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .api import share_cards_router
from .http import RenderRequestGuardMiddleware
from .services.share_cards import get_render_pool, shutdown_render_pool
from .settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    yield
    # Let in-flight cards finish rather than dropping a user's share request.
    shutdown_render_pool(wait=True)


app = FastAPI(
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
)
app.add_middleware(
    RenderRequestGuardMiddleware,
    max_body_bytes=settings.http_max_request_bytes,
    rate_limit_per_minute=settings.http_rate_limit_per_minute,
)

static_file_path = os.path.dirname(os.path.realpath(__file__)) + "/static"
app.mount("/static", StaticFiles(directory=static_file_path), name="static")

app.include_router(share_cards_router)


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse("/health" if settings.is_production else "/docs")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> dict[str, int | str]:
    stats = get_render_pool().stats()
    return {"status": "ready", "capacity": stats["capacity"], "available": stats["available"]}
