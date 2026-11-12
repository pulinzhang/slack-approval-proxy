"""Trace table rows."""

from typing import TypedDict


class ExchangeRow(TypedDict):
    exchange_id: str
    correlation_id: str
    request_id: str | None
    direction: str
    source_system: str
    target_system: str
    operation: str
    http_method: str
    url: str
    request_headers: str
    request_body: str | None
    sent_at: str
    exchange_status: str
    http_status: int | None
    response_headers: str | None
    response_body: str | None
    received_at: str | None
    duration_ms: int | None
    business_outcome: str | None
    error_message: str | None
    body_truncated: int
    attempt: int


class HttpCallRow(TypedDict):
    id: int
    exchange_id: str | None
    correlation_id: str | None
    request_id: str | None
    direction: str
    source_system: str
    target_system: str
    operation: str
    http_method: str
    url: str
    http_status: int | None
    duration_ms: int | None
    error_message: str | None
    called_at: str


class AuditRow(TypedDict):
    id: int
    correlation_id: str
    request_id: str
    from_status: str | None
    to_status: str
    actor: str
    reason: str
    created_at: str
