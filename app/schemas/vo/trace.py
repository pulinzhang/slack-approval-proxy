"""Trace HTTP bodies."""

from pydantic import BaseModel, ConfigDict


class ExchangeSummary(BaseModel):
    model_config = ConfigDict()

    exchange_id: str
    correlation_id: str
    request_id: str | None
    direction: str
    source_system: str
    target_system: str
    operation: str
    http_method: str
    url: str
    exchange_status: str
    http_status: int | None
    business_outcome: str | None
    sent_at: str
    received_at: str | None
    duration_ms: int | None
    attempt: int


class ExchangeList(BaseModel):
    model_config = ConfigDict()

    items: list[ExchangeSummary]
    page: int
    size: int
    total: int


class HttpCallLog(BaseModel):
    model_config = ConfigDict()

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


class BusinessAudit(BaseModel):
    model_config = ConfigDict()

    id: int
    correlation_id: str
    request_id: str
    from_status: str | None
    to_status: str
    actor: str
    reason: str
    created_at: str


class ExchangeRecord(BaseModel):
    model_config = ConfigDict()

    exchange_id: str
    correlation_id: str
    request_id: str | None
    direction: str
    source_system: str
    target_system: str
    operation: str
    http_method: str
    url: str
    request_headers: dict[str, str]
    request_body: str | None
    sent_at: str
    exchange_status: str
    http_status: int | None
    response_headers: dict[str, str] | None
    response_body: str | None
    received_at: str | None
    duration_ms: int | None
    business_outcome: str | None
    error_message: str | None
    body_truncated: int
    attempt: int


class ExchangeDetail(BaseModel):
    model_config = ConfigDict()

    exchange_id: str
    correlation_id: str
    request_id: str | None
    direction: str
    source_system: str
    target_system: str
    operation: str
    http_method: str
    url: str
    request_headers: dict[str, str]
    request_body: str | None
    sent_at: str
    exchange_status: str
    http_status: int | None
    response_headers: dict[str, str] | None
    response_body: str | None
    received_at: str | None
    duration_ms: int | None
    business_outcome: str | None
    error_message: str | None
    body_truncated: int
    attempt: int
    http_call_logs: list[HttpCallLog]
    business_audit_logs: list[BusinessAudit]


class ApprovalTrace(BaseModel):
    model_config = ConfigDict()

    correlation_id: str
    message_exchanges: list[ExchangeRecord]
    http_call_logs: list[HttpCallLog]
    business_audit_logs: list[BusinessAudit]


class SystemNode(BaseModel):
    model_config = ConfigDict()

    system: str
    last_sent_at: str
    last_business_outcome: str | None


class ExchangeSummaryReport(BaseModel):
    model_config = ConfigDict()

    exchanges_total: int
    exchanges_succeeded: int
    exchanges_failed: int
    exchanges_open: int
    approvals_pending: int
    systems: list[SystemNode]
