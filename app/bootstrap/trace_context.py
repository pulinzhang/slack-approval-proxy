"""One trace context per request, cleared after the response."""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.services.message_trace.service import reset_request_trace, restore_request_trace


class TraceContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        tokens = reset_request_trace()
        try:
            return await call_next(request)
        finally:
            restore_request_trace(tokens)


def register_trace_context(app: FastAPI) -> None:
    app.add_middleware(TraceContextMiddleware)
