"""Trace table reads and writes. Callers commit."""

import sqlite3

from app.models.message_trace.row import AuditRow, ExchangeRow, HttpCallRow

_EXCHANGE_COLUMNS = """
    exchange_id, correlation_id, request_id, direction, source_system, target_system,
    operation, http_method, url, request_headers, request_body, sent_at, exchange_status,
    http_status, response_headers, response_body, received_at, duration_ms,
    business_outcome, error_message, body_truncated, attempt
"""

_OPERATOR_OPERATIONS = ("list_exchanges", "get_exchange", "read_trace", "read_summary")


def insert_exchange(
    connection: sqlite3.Connection,
    exchange_id: str,
    correlation_id: str,
    request_id: str | None,
    direction: str,
    source_system: str,
    target_system: str,
    operation: str,
    http_method: str,
    url: str,
    request_headers: str,
    request_body: str | None,
    sent_at: str,
    exchange_status: str,
    body_truncated: int,
    attempt: int,
) -> None:
    connection.execute(
        """
        INSERT INTO message_exchanges (
            exchange_id, correlation_id, request_id, direction, source_system, target_system,
            operation, http_method, url, request_headers, request_body, sent_at,
            exchange_status, body_truncated, attempt
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            exchange_id,
            correlation_id,
            request_id,
            direction,
            source_system,
            target_system,
            operation,
            http_method,
            url,
            request_headers,
            request_body,
            sent_at,
            exchange_status,
            body_truncated,
            attempt,
        ),
    )


def complete_exchange(
    connection: sqlite3.Connection,
    exchange_id: str,
    exchange_status: str,
    http_status: int | None,
    response_headers: str | None,
    response_body: str | None,
    received_at: str,
    duration_ms: int,
    business_outcome: str,
    error_message: str | None,
    body_truncated: int,
) -> None:
    connection.execute(
        """
        UPDATE message_exchanges
        SET exchange_status = ?, http_status = ?, response_headers = ?, response_body = ?,
            received_at = ?, duration_ms = ?, business_outcome = ?, error_message = ?,
            body_truncated = CASE WHEN body_truncated = 1 OR ? = 1 THEN 1 ELSE 0 END
        WHERE exchange_id = ?
        """,
        (
            exchange_status,
            http_status,
            response_headers,
            response_body,
            received_at,
            duration_ms,
            business_outcome,
            error_message,
            body_truncated,
            exchange_id,
        ),
    )


def insert_http_call(
    connection: sqlite3.Connection,
    exchange_id: str,
    correlation_id: str,
    request_id: str | None,
    direction: str,
    source_system: str,
    target_system: str,
    operation: str,
    http_method: str,
    url: str,
    http_status: int | None,
    duration_ms: int | None,
    error_message: str | None,
    called_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO http_call_logs (
            exchange_id, correlation_id, request_id, direction, source_system, target_system,
            operation, http_method, url, http_status, duration_ms, error_message, called_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            exchange_id,
            correlation_id,
            request_id,
            direction,
            source_system,
            target_system,
            operation,
            http_method,
            url,
            http_status,
            duration_ms,
            error_message,
            called_at,
        ),
    )


def insert_audit(
    connection: sqlite3.Connection,
    correlation_id: str,
    request_id: str,
    from_status: str | None,
    to_status: str,
    actor: str,
    reason: str,
    created_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO business_audit_logs (
            correlation_id, request_id, from_status, to_status, actor, reason, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (correlation_id, request_id, from_status, to_status, actor, reason, created_at),
    )


def get_exchange(connection: sqlite3.Connection, exchange_id: str) -> ExchangeRow | None:
    row = connection.execute(
        f"SELECT {_EXCHANGE_COLUMNS} FROM message_exchanges WHERE exchange_id = ?",
        (exchange_id,),
    ).fetchone()
    if row is None:
        return None
    return _exchange(row)


def list_exchanges(
    connection: sqlite3.Connection,
    request_id: str | None,
    correlation_id: str | None,
    direction: str | None,
    exchange_status: str | None,
    business_outcome: str | None,
    operation: str | None,
    include_operator_reads: bool,
    limit: int,
    offset: int,
) -> list[ExchangeRow]:
    clause, params = _filters(
        request_id,
        correlation_id,
        direction,
        exchange_status,
        business_outcome,
        operation,
        include_operator_reads,
    )
    rows = connection.execute(
        f"""
        SELECT {_EXCHANGE_COLUMNS} FROM message_exchanges
        WHERE {clause}
        ORDER BY sent_at DESC, exchange_id DESC
        LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    ).fetchall()
    return [_exchange(row) for row in rows]


def count_exchanges(
    connection: sqlite3.Connection,
    request_id: str | None,
    correlation_id: str | None,
    direction: str | None,
    exchange_status: str | None,
    business_outcome: str | None,
    operation: str | None,
    include_operator_reads: bool,
) -> int:
    clause, params = _filters(
        request_id,
        correlation_id,
        direction,
        exchange_status,
        business_outcome,
        operation,
        include_operator_reads,
    )
    return _count(
        connection, f"SELECT COUNT(*) AS total FROM message_exchanges WHERE {clause}", params
    )


def count_succeeded(connection: sqlite3.Connection, include_operator_reads: bool) -> int:
    clause, params = _filters(None, None, None, None, None, None, include_operator_reads)
    return _count(
        connection,
        f"""
        SELECT COUNT(*) AS total FROM message_exchanges
        WHERE {clause} AND exchange_status = 'completed' AND business_outcome = 'succeeded'
        """,
        params,
    )


def count_failed(connection: sqlite3.Connection, include_operator_reads: bool) -> int:
    clause, params = _filters(None, None, None, None, None, None, include_operator_reads)
    return _count(
        connection,
        f"""
        SELECT COUNT(*) AS total FROM message_exchanges
        WHERE {clause}
          AND (business_outcome = 'failed'
               OR exchange_status IN ('timeout', 'transport_failed'))
        """,
        params,
    )


def count_open(connection: sqlite3.Connection, include_operator_reads: bool) -> int:
    clause, params = _filters(None, None, None, None, None, None, include_operator_reads)
    return _count(
        connection,
        f"""
        SELECT COUNT(*) AS total FROM message_exchanges
        WHERE {clause} AND exchange_status IN ('received', 'sent')
        """,
        params,
    )


def system_nodes(
    connection: sqlite3.Connection, include_operator_reads: bool
) -> list[tuple[str, str, str | None]]:
    clause, params = _filters(None, None, None, None, None, None, include_operator_reads)
    rows = connection.execute(
        f"""
        SELECT source_system, target_system, sent_at, business_outcome
        FROM message_exchanges
        WHERE {clause}
        ORDER BY sent_at ASC, exchange_id ASC
        """,
        params,
    ).fetchall()
    latest: dict[str, tuple[str, str | None]] = {}
    for row in rows:
        sent_at = _text(row, "sent_at")
        outcome = _optional_text(row, "business_outcome")
        for key in (_text(row, "source_system"), _text(row, "target_system")):
            latest[key] = (sent_at, outcome)
    return [(system, sent_at, outcome) for system, (sent_at, outcome) in sorted(latest.items())]


def list_for_request(connection: sqlite3.Connection, request_id: str) -> list[ExchangeRow]:
    rows = connection.execute(
        f"""
        SELECT {_EXCHANGE_COLUMNS} FROM message_exchanges
        WHERE request_id = ?
        ORDER BY sent_at ASC, exchange_id ASC
        """,
        (request_id,),
    ).fetchall()
    return [_exchange(row) for row in rows]


def list_edges(
    connection: sqlite3.Connection, include_operator_reads: bool, limit: int
) -> list[tuple[str, str]]:
    clause, params = _filters(None, None, None, None, None, None, include_operator_reads)
    rows = connection.execute(
        f"""
        SELECT DISTINCT source_system, target_system FROM message_exchanges
        WHERE {clause}
        ORDER BY source_system ASC, target_system ASC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    return [(_text(row, "source_system"), _text(row, "target_system")) for row in rows]


def http_calls_for_exchange(connection: sqlite3.Connection, exchange_id: str) -> list[HttpCallRow]:
    rows = connection.execute(
        """
        SELECT id, exchange_id, correlation_id, request_id, direction, source_system,
               target_system, operation, http_method, url, http_status, duration_ms,
               error_message, called_at
        FROM http_call_logs
        WHERE exchange_id = ?
        ORDER BY called_at ASC, id ASC
        """,
        (exchange_id,),
    ).fetchall()
    return [_http_call(row) for row in rows]


def http_calls_for_request(connection: sqlite3.Connection, request_id: str) -> list[HttpCallRow]:
    rows = connection.execute(
        """
        SELECT id, exchange_id, correlation_id, request_id, direction, source_system,
               target_system, operation, http_method, url, http_status, duration_ms,
               error_message, called_at
        FROM http_call_logs
        WHERE request_id = ?
        ORDER BY called_at ASC, id ASC
        """,
        (request_id,),
    ).fetchall()
    return [_http_call(row) for row in rows]


def audits_for_request(connection: sqlite3.Connection, request_id: str) -> list[AuditRow]:
    rows = connection.execute(
        """
        SELECT id, correlation_id, request_id, from_status, to_status, actor, reason, created_at
        FROM business_audit_logs
        WHERE request_id = ?
        ORDER BY created_at ASC, id ASC
        """,
        (request_id,),
    ).fetchall()
    return [_audit(row) for row in rows]


def count_pending_approvals(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT COUNT(*) AS total FROM approval_requests WHERE status = 'pending'"
    ).fetchone()
    if row is None:
        return 0
    value = row["total"]
    if not isinstance(value, int):
        raise TypeError("total")
    return value


def timeout_abandoned(connection: sqlite3.Connection, cutoff: str, in_flight: set[str]) -> None:
    rows = connection.execute(
        """
        SELECT exchange_id FROM message_exchanges
        WHERE exchange_status IN ('sent', 'received') AND sent_at < ?
        """,
        (cutoff,),
    ).fetchall()
    for row in rows:
        exchange_id = _text(row, "exchange_id")
        if exchange_id in in_flight:
            continue
        connection.execute(
            """
            UPDATE message_exchanges
            SET exchange_status = 'timeout', business_outcome = 'unknown'
            WHERE exchange_id = ? AND exchange_status IN ('sent', 'received')
            """,
            (exchange_id,),
        )


def purge(connection: sqlite3.Connection, http_cutoff: str, trace_cutoff: str) -> None:
    connection.execute("DELETE FROM http_call_logs WHERE called_at < ?", (http_cutoff,))
    connection.execute("DELETE FROM message_exchanges WHERE sent_at < ?", (trace_cutoff,))
    connection.execute("DELETE FROM business_audit_logs WHERE created_at < ?", (trace_cutoff,))


def _filters(
    request_id: str | None,
    correlation_id: str | None,
    direction: str | None,
    exchange_status: str | None,
    business_outcome: str | None,
    operation: str | None,
    include_operator_reads: bool,
) -> tuple[str, tuple[str, ...]]:
    clauses = ["1 = 1"]
    params: list[str] = []
    if request_id is not None:
        clauses.append("request_id = ?")
        params.append(request_id)
    if correlation_id is not None:
        clauses.append("correlation_id = ?")
        params.append(correlation_id)
    if direction is not None:
        clauses.append("direction = ?")
        params.append(direction)
    if exchange_status is not None:
        clauses.append("exchange_status = ?")
        params.append(exchange_status)
    if business_outcome is not None:
        clauses.append("business_outcome = ?")
        params.append(business_outcome)
    if operation is not None:
        clauses.append("operation = ?")
        params.append(operation)
    if not include_operator_reads:
        marks = ", ".join("?" for _ in _OPERATOR_OPERATIONS)
        clauses.append(f"operation NOT IN ({marks})")
        params.extend(_OPERATOR_OPERATIONS)
    return " AND ".join(clauses), tuple(params)


def _count(connection: sqlite3.Connection, sql: str, params: tuple[str, ...]) -> int:
    row = connection.execute(sql, params).fetchone()
    if row is None:
        return 0
    value = row["total"]
    if not isinstance(value, int):
        raise TypeError("total")
    return value


def _exchange(row: sqlite3.Row) -> ExchangeRow:
    return ExchangeRow(
        exchange_id=_text(row, "exchange_id"),
        correlation_id=_text(row, "correlation_id"),
        request_id=_optional_text(row, "request_id"),
        direction=_text(row, "direction"),
        source_system=_text(row, "source_system"),
        target_system=_text(row, "target_system"),
        operation=_text(row, "operation"),
        http_method=_text(row, "http_method"),
        url=_text(row, "url"),
        request_headers=_text(row, "request_headers"),
        request_body=_optional_text(row, "request_body"),
        sent_at=_text(row, "sent_at"),
        exchange_status=_text(row, "exchange_status"),
        http_status=_optional_int(row, "http_status"),
        response_headers=_optional_text(row, "response_headers"),
        response_body=_optional_text(row, "response_body"),
        received_at=_optional_text(row, "received_at"),
        duration_ms=_optional_int(row, "duration_ms"),
        business_outcome=_optional_text(row, "business_outcome"),
        error_message=_optional_text(row, "error_message"),
        body_truncated=_required_int(row, "body_truncated"),
        attempt=_required_int(row, "attempt"),
    )


def _http_call(row: sqlite3.Row) -> HttpCallRow:
    return HttpCallRow(
        id=_required_int(row, "id"),
        exchange_id=_optional_text(row, "exchange_id"),
        correlation_id=_optional_text(row, "correlation_id"),
        request_id=_optional_text(row, "request_id"),
        direction=_text(row, "direction"),
        source_system=_text(row, "source_system"),
        target_system=_text(row, "target_system"),
        operation=_text(row, "operation"),
        http_method=_text(row, "http_method"),
        url=_text(row, "url"),
        http_status=_optional_int(row, "http_status"),
        duration_ms=_optional_int(row, "duration_ms"),
        error_message=_optional_text(row, "error_message"),
        called_at=_text(row, "called_at"),
    )


def _audit(row: sqlite3.Row) -> AuditRow:
    return AuditRow(
        id=_required_int(row, "id"),
        correlation_id=_text(row, "correlation_id"),
        request_id=_text(row, "request_id"),
        from_status=_optional_text(row, "from_status"),
        to_status=_text(row, "to_status"),
        actor=_text(row, "actor"),
        reason=_text(row, "reason"),
        created_at=_text(row, "created_at"),
    )


def _text(row: sqlite3.Row, key: str) -> str:
    value = row[key]
    if not isinstance(value, str):
        raise TypeError(key)
    return value


def _optional_text(row: sqlite3.Row, key: str) -> str | None:
    value = row[key]
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(key)
    return value


def _optional_int(row: sqlite3.Row, key: str) -> int | None:
    value = row[key]
    if value is None:
        return None
    if not isinstance(value, int):
        raise TypeError(key)
    return value


def _required_int(row: sqlite3.Row, key: str) -> int:
    value = row[key]
    if not isinstance(value, int):
        raise TypeError(key)
    return value
