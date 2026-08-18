"""Small ASGI guards for the optional HTTP rendering surface."""

import time
from collections import deque
from threading import Lock
from typing import ClassVar

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RenderRequestGuardMiddleware:
    """Reject oversized or excessive render requests before JSON parsing.

    Production still places this API behind service authentication and an edge
    rate limiter. The process-local limiter is a final line of defence and is
    deliberately global because the expected caller is one backend service.
    """

    _RENDER_PATHS: ClassVar[frozenset[str]] = frozenset({"/share-cards/render", "/share-cards/preview"})

    def __init__(self, app: ASGIApp, max_body_bytes: int, rate_limit_per_minute: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.rate_limit_per_minute = rate_limit_per_minute
        self._admissions: deque[float] = deque()
        self._lock = Lock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") != "POST" or scope.get("path") not in self._RENDER_PATHS:
            await self.app(scope, receive, send)
            return

        if not self._admit():
            await JSONResponse(
                {"detail": "Render request rate limit exceeded"},
                status_code=429,
                headers={"Retry-After": "60"},
            )(scope, receive, send)
            return

        content_length = _content_length(scope)
        if content_length is not None and content_length > self.max_body_bytes:
            await self._too_large(scope, receive, send)
            return

        body = bytearray()
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            body.extend(chunk)
            if len(body) > self.max_body_bytes:
                await self._too_large(scope, receive, send)
                return
            more_body = bool(message.get("more_body", False))

        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if delivered:
                return {"type": "http.request", "body": b"", "more_body": False}
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay, send)

    def _admit(self) -> bool:
        cutoff = time.monotonic() - 60
        with self._lock:
            while self._admissions and self._admissions[0] <= cutoff:
                self._admissions.popleft()
            if len(self._admissions) >= self.rate_limit_per_minute:
                return False
            self._admissions.append(time.monotonic())
            return True

    async def _too_large(self, scope: Scope, receive: Receive, send: Send) -> None:
        await JSONResponse(
            {"detail": f"Request body exceeds {self.max_body_bytes} bytes"},
            status_code=413,
        )(scope, receive, send)


def _content_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", []):
        if name.lower() == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None
