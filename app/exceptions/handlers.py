"""Map exceptions to the design JSON envelope and finish an open exchange."""

import json
import logging

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.common.auth import header_map
from app.exceptions.base import AppError, ConflictError, InvalidSignatureError, MessageTraceError
from app.services.message_trace.service import OPERATOR_SYSTEM, settle_rejection

logger = logging.getLogger(__name__)
_TRACE_FAILURE = {
    "error": "MessageTraceError",
    "message": "Failed to record the exchange",
}


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    body: dict[str, str] = {"error": exc.error, "message": exc.message}
    if isinstance(exc, ConflictError):
        body["request_id"] = exc.request_id
    if isinstance(exc, InvalidSignatureError):
        return JSONResponse(status_code=exc.status_code, content=body)
    failed = await _record(request, exc.status_code, body)
    if failed is not None:
        return failed
    return JSONResponse(status_code=exc.status_code, content=body)


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    payload = {"error": "ValidationError", "message": _first_validation_message(exc)}
    failed = await _record(request, 422, payload)
    if failed is not None:
        return failed
    return JSONResponse(status_code=422, content=payload)


async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    error = "NotFound" if exc.status_code == 404 else "HTTPError"
    return JSONResponse(status_code=exc.status_code, content={"error": error, "message": message})


async def generic_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"error": "InternalError", "message": "Internal server error"},
    )


async def _record(
    request: Request, status_code: int, payload: dict[str, str]
) -> JSONResponse | None:
    if not request.url.path.startswith("/api/"):
        return None
    try:
        raw = (await request.body()).decode("utf-8")
    except UnicodeDecodeError:
        raw = ""
    request_id, source = _caller(raw, request.url.path)
    try:
        settle_rejection(
            status_code,
            payload,
            request.method,
            request.url.path,
            header_map(list(request.headers.items())),
            raw or None,
            _operation(request.method, request.url.path),
            source,
            request_id,
        )
    except MessageTraceError:
        return JSONResponse(status_code=503, content=_TRACE_FAILURE)
    return None


def _caller(raw: str, path: str) -> tuple[str | None, str]:
    if path.startswith("/api/v1/message-exchanges"):
        return _json_request_id(raw), OPERATOR_SYSTEM
    if path.startswith("/api/v1/slack"):
        return _json_request_id(raw), "slack"
    request_id = _json_request_id(raw)
    source = _json_text(raw, "system_source") or "external"
    return request_id, source


def _operation(method: str, path: str) -> str:
    if path == "/api/v1/approvals" and method == "POST":
        return "create_approval"
    if path.endswith("/trace"):
        return "read_trace"
    if path.startswith("/api/v1/approvals/"):
        return "get_approval"
    if path == "/api/v1/message-exchanges/summary":
        return "read_summary"
    if path == "/api/v1/message-exchanges":
        return "list_exchanges"
    if path.startswith("/api/v1/message-exchanges/"):
        return "get_exchange"
    return "slack_interactive"


def _json_request_id(raw: str) -> str | None:
    return _json_text(raw, "request_id")


def _json_text(raw: str, key: str) -> str | None:
    if raw == "":
        return None
    try:
        parsed: object = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    value = parsed.get(key)
    return value if isinstance(value, str) else None


def _first_validation_message(exc: RequestValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "body: request is invalid"
    first = errors[0]
    location = first.get("loc", ())
    field = str(location[-1]) if isinstance(location, tuple) and location else "body"
    reason = str(first.get("msg", "invalid"))
    prefix = "Value error, "
    if reason.startswith(prefix):
        reason = reason.removeprefix(prefix)
    return f"{field}: {reason}"
