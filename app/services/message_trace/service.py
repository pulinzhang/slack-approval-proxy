"""Record and read the three trace logs."""

import json
import logging
import sqlite3
from contextvars import ContextVar, Token
from dataclasses import dataclass
from uuid import uuid4

from app.common.clock import format_utc, parse_utc, utc_now
from app.common.locks import exchange_ids_in_flight, mark_exchange, unmark_exchange
from app.database import read_connection, transaction
from app.exceptions.base import MessageTraceError, NotFoundError, ValidationFailure
from app.models.message_trace.row import AuditRow, ExchangeRow, HttpCallRow
from app.repositories.message_trace import repository as trace_repo
from app.schemas.vo.trace import (
    ApprovalTrace,
    BusinessAudit,
    ExchangeDetail,
    ExchangeList,
    ExchangeRecord,
    ExchangeSummary,
    ExchangeSummaryReport,
    HttpCallLog,
    SystemNode,
)
from app.services.message_trace.mask import headers_object, mask_body, mask_headers

logger = logging.getLogger(__name__)

PROXY_SYSTEM = "slack-approval-proxy"
OPERATOR_SYSTEM = "operator-ui"
_inbound_id: ContextVar[str | None] = ContextVar("inbound_exchange_id", default=None)
_finished: ContextVar[bool] = ContextVar("inbound_exchange_finished", default=False)


@dataclass(frozen=True)
class ExchangeQuery:
    request_id: str | None
    correlation_id: str | None
    direction: str | None
    exchange_status: str | None
    business_outcome: str | None
    operation: str | None
    page: int
    size: int
    include_operator_reads: bool


def reset_request_trace() -> tuple[Token[str | None], Token[bool]]:
    return _inbound_id.set(None), _finished.set(False)


def restore_request_trace(tokens: tuple[Token[str | None], Token[bool]]) -> None:
    _inbound_id.reset(tokens[0])
    _finished.reset(tokens[1])


def begin_inbound(
    correlation_id: str,
    request_id: str | None,
    source_system: str,
    operation: str,
    http_method: str,
    url: str,
    headers: dict[str, str],
    body: str | None,
    attempt: int = 1,
) -> str:
    return _begin(
        correlation_id,
        request_id,
        "inbound",
        source_system,
        PROXY_SYSTEM,
        operation,
        http_method,
        url,
        headers,
        body,
        "received",
        attempt,
        bind_request=True,
    )


def begin_outbound(
    correlation_id: str,
    request_id: str | None,
    target_system: str,
    operation: str,
    http_method: str,
    url: str,
    headers: dict[str, str],
    body: str | None,
    attempt: int = 1,
) -> str:
    return _begin(
        correlation_id,
        request_id,
        "outbound",
        PROXY_SYSTEM,
        target_system,
        operation,
        http_method,
        url,
        headers,
        body,
        "sent",
        attempt,
        bind_request=False,
    )


def complete_call(
    exchange_id: str,
    exchange_status: str,
    http_status: int | None,
    response_headers: dict[str, str] | None,
    response_body: str | None,
    business_outcome: str,
    error_message: str | None,
) -> None:
    received_at = format_utc(utc_now())
    body, truncated = mask_body(response_body)
    header_json = mask_headers(response_headers) if response_headers is not None else None
    wrote = False
    for _ in range(3):
        try:
            with transaction() as connection:
                row = trace_repo.get_exchange(connection, exchange_id)
                if row is None:
                    return
                duration_ms = _duration_ms(row["sent_at"], received_at)
                trace_repo.complete_exchange(
                    connection,
                    exchange_id,
                    exchange_status,
                    http_status,
                    header_json,
                    body,
                    received_at,
                    duration_ms,
                    business_outcome,
                    error_message,
                    truncated,
                )
            wrote = True
            break
        except sqlite3.Error:
            wrote = False
    unmark_exchange(exchange_id)
    if not wrote:
        logger.error("message_trace_write_failed")
        _finish_if_inbound(exchange_id)
        return
    _write_http_log(exchange_id, http_status, received_at, error_message)
    _finish_if_inbound(exchange_id)


def audit_change(
    connection: sqlite3.Connection,
    correlation_id: str,
    request_id: str,
    from_status: str | None,
    to_status: str,
    actor: str,
    reason: str,
) -> None:
    trace_repo.insert_audit(
        connection,
        correlation_id,
        request_id,
        from_status,
        to_status,
        actor,
        reason,
        format_utc(utc_now()),
    )


def settle_rejection(
    status_code: int,
    payload: dict[str, str],
    method: str,
    url: str,
    headers: dict[str, str],
    body: str | None,
    operation: str,
    source_system: str,
    request_id: str | None,
) -> None:
    if _finished.get():
        return
    response_body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    outcome = "failed" if "error" in payload else "succeeded"
    open_id = _inbound_id.get()
    if open_id is not None:
        complete_call(
            open_id,
            "completed",
            status_code,
            {"content-type": "application/json"},
            response_body,
            outcome,
            None,
        )
        return
    if status_code not in {401, 422}:
        return
    exchange_id = begin_inbound(
        str(uuid4()),
        request_id,
        source_system,
        operation,
        method,
        url,
        headers,
        body,
    )
    complete_call(
        exchange_id,
        "completed",
        status_code,
        {"content-type": "application/json"},
        response_body,
        outcome,
        None,
    )


def list_messages(query: ExchangeQuery) -> ExchangeList:
    _check_page(query.page, query.size)
    exchange_id = begin_inbound(
        query.correlation_id or str(uuid4()),
        query.request_id,
        OPERATOR_SYSTEM,
        "list_exchanges",
        "GET",
        "/api/v1/message-exchanges",
        {},
        None,
    )
    with read_connection() as connection:
        total = trace_repo.count_exchanges(
            connection,
            query.request_id,
            query.correlation_id,
            query.direction,
            query.exchange_status,
            query.business_outcome,
            query.operation,
            query.include_operator_reads,
        )
        rows = trace_repo.list_exchanges(
            connection,
            query.request_id,
            query.correlation_id,
            query.direction,
            query.exchange_status,
            query.business_outcome,
            query.operation,
            query.include_operator_reads,
            query.size,
            (query.page - 1) * query.size,
        )
    result = ExchangeList(
        items=[_summary(row) for row in rows],
        page=query.page,
        size=query.size,
        total=total,
    )
    complete_call(
        exchange_id,
        "completed",
        200,
        {"content-type": "application/json"},
        result.model_dump_json(),
        "succeeded",
        None,
    )
    return result


def get_message(exchange_id: str) -> ExchangeDetail:
    recorded = begin_inbound(
        str(uuid4()),
        None,
        OPERATOR_SYSTEM,
        "get_exchange",
        "GET",
        f"/api/v1/message-exchanges/{exchange_id}",
        {},
        None,
    )
    with read_connection() as connection:
        row = trace_repo.get_exchange(connection, exchange_id)
        logs = trace_repo.http_calls_for_exchange(connection, exchange_id) if row else []
        audits = (
            trace_repo.audits_for_request(connection, row["request_id"])
            if row and row["request_id"]
            else []
        )
    if row is None:
        payload = {"error": "NotFound", "message": "Message exchange not found"}
        complete_call(
            recorded,
            "completed",
            404,
            {"content-type": "application/json"},
            json.dumps(payload),
            "failed",
            None,
        )
        raise NotFoundError("Message exchange not found")
    detail = ExchangeDetail(
        **_record(row).model_dump(),
        http_call_logs=[_http_log(item) for item in logs],
        business_audit_logs=[_audit(item) for item in audits],
    )
    complete_call(
        recorded,
        "completed",
        200,
        {"content-type": "application/json"},
        detail.model_dump_json(),
        "succeeded",
        None,
    )
    return detail


def summarize(include_operator_reads: bool) -> ExchangeSummaryReport:
    exchange_id = begin_inbound(
        str(uuid4()),
        None,
        OPERATOR_SYSTEM,
        "read_summary",
        "GET",
        "/api/v1/message-exchanges/summary",
        {},
        None,
    )
    with read_connection() as connection:
        report = ExchangeSummaryReport(
            exchanges_total=trace_repo.count_exchanges(
                connection, None, None, None, None, None, None, include_operator_reads
            ),
            exchanges_succeeded=trace_repo.count_succeeded(connection, include_operator_reads),
            exchanges_failed=trace_repo.count_failed(connection, include_operator_reads),
            exchanges_open=trace_repo.count_open(connection, include_operator_reads),
            approvals_pending=trace_repo.count_pending_approvals(connection),
            systems=[
                SystemNode(system=system, last_sent_at=sent_at, last_business_outcome=outcome)
                for system, sent_at, outcome in trace_repo.system_nodes(
                    connection, include_operator_reads
                )
            ],
        )
    complete_call(
        exchange_id,
        "completed",
        200,
        {"content-type": "application/json"},
        report.model_dump_json(),
        "succeeded",
        None,
    )
    return report


def read_chain(request_id: str, correlation_id: str | None) -> ApprovalTrace:
    exchange_id = begin_inbound(
        correlation_id or str(uuid4()),
        request_id,
        OPERATOR_SYSTEM,
        "read_trace",
        "GET",
        f"/api/v1/approvals/{request_id}/trace",
        {},
        None,
    )
    if correlation_id is None:
        payload = {"error": "NotFound", "message": "Approval request not found"}
        complete_call(
            exchange_id,
            "completed",
            404,
            {"content-type": "application/json"},
            json.dumps(payload),
            "failed",
            None,
        )
        raise NotFoundError()
    with read_connection() as connection:
        trace = ApprovalTrace(
            correlation_id=correlation_id,
            message_exchanges=[
                _record(row) for row in trace_repo.list_for_request(connection, request_id)
            ],
            http_call_logs=[
                _http_log(row) for row in trace_repo.http_calls_for_request(connection, request_id)
            ],
            business_audit_logs=[
                _audit(row) for row in trace_repo.audits_for_request(connection, request_id)
            ],
        )
    complete_call(
        exchange_id,
        "completed",
        200,
        {"content-type": "application/json"},
        trace.model_dump_json(),
        "succeeded",
        None,
    )
    return trace


def list_edges(include_operator_reads: bool) -> list[tuple[str, str]]:
    with read_connection() as connection:
        return trace_repo.list_edges(connection, include_operator_reads, 100)


def timeout_open_exchanges(cutoff: str) -> None:
    with transaction() as connection:
        trace_repo.timeout_abandoned(connection, cutoff, exchange_ids_in_flight())


def purge_expired(http_cutoff: str, trace_cutoff: str) -> None:
    with transaction() as connection:
        trace_repo.purge(connection, http_cutoff, trace_cutoff)


def proxy_outcome(body: str) -> str:
    try:
        parsed: object = json.loads(body) if body else None
    except json.JSONDecodeError:
        return "succeeded"
    if isinstance(parsed, dict) and "error" in parsed:
        return "failed"
    return "succeeded"


def external_outcome(http_status: int | None, body: str | None, transport_failed: bool) -> str:
    if transport_failed or http_status is None:
        return "unknown"
    if http_status < 200 or http_status >= 300:
        return "failed"
    try:
        parsed: object = json.loads(body) if body else None
    except json.JSONDecodeError:
        return "succeeded"
    if isinstance(parsed, dict) and (parsed.get("success") is False or "error" in parsed):
        return "failed"
    return "succeeded"


def _begin(
    correlation_id: str,
    request_id: str | None,
    direction: str,
    source_system: str,
    target_system: str,
    operation: str,
    http_method: str,
    url: str,
    headers: dict[str, str],
    body: str | None,
    exchange_status: str,
    attempt: int,
    bind_request: bool,
) -> str:
    exchange_id = str(uuid4())
    stored_body, truncated = mask_body(body)
    try:
        with transaction() as connection:
            trace_repo.insert_exchange(
                connection,
                exchange_id,
                correlation_id,
                request_id,
                direction,
                source_system,
                target_system,
                operation,
                http_method,
                _path_only(url),
                mask_headers(headers),
                stored_body,
                format_utc(utc_now()),
                exchange_status,
                truncated,
                attempt,
            )
    except sqlite3.Error as exc:
        raise MessageTraceError() from exc
    mark_exchange(exchange_id)
    if bind_request:
        _inbound_id.set(exchange_id)
    return exchange_id


def _write_http_log(
    exchange_id: str, http_status: int | None, called_at: str, error_message: str | None
) -> None:
    try:
        with transaction() as connection:
            row = trace_repo.get_exchange(connection, exchange_id)
            if row is None:
                return
            trace_repo.insert_http_call(
                connection,
                exchange_id,
                row["correlation_id"],
                row["request_id"],
                row["direction"],
                row["source_system"],
                row["target_system"],
                row["operation"],
                row["http_method"],
                row["url"],
                http_status,
                row["duration_ms"],
                error_message,
                called_at,
            )
    except sqlite3.Error:
        logger.error("message_trace_write_failed")


def _finish_if_inbound(exchange_id: str) -> None:
    if _inbound_id.get() == exchange_id:
        _inbound_id.set(None)
        _finished.set(True)


def _check_page(page: int, size: int) -> None:
    if page < 1:
        raise ValidationFailure("page: must be an integer from 1")
    if not 1 <= size <= 100:
        raise ValidationFailure("size: must be an integer from 1 to 100")


def _duration_ms(sent_at: str, received_at: str) -> int:
    return max(0, int((parse_utc(received_at) - parse_utc(sent_at)).total_seconds() * 1000))


def _path_only(url: str) -> str:
    return url.split("?", 1)[0]


def _summary(row: ExchangeRow) -> ExchangeSummary:
    return ExchangeSummary.model_validate(dict(row))


def _record(row: ExchangeRow) -> ExchangeRecord:
    payload = dict(row)
    payload["request_headers"] = headers_object(row["request_headers"]) or {}
    payload["response_headers"] = headers_object(row["response_headers"])
    return ExchangeRecord.model_validate(payload)


def _http_log(row: HttpCallRow) -> HttpCallLog:
    return HttpCallLog.model_validate(dict(row))


def _audit(row: AuditRow) -> BusinessAudit:
    return BusinessAudit.model_validate(dict(row))
