"""approval_requests reads and conditional writes. Callers commit."""

import sqlite3

from app.models.approval.row import ApprovalRow

_COLUMNS = """
    request_id, correlation_id, system_source, callback_url, title, details, status,
    slack_channel_id, slack_message_ts, decided_by, decided_at, expires_at, created_at,
    callback_state, callback_delivered_at, callback_error_log, card_updated_at
"""


def get(connection: sqlite3.Connection, request_id: str) -> ApprovalRow | None:
    row = connection.execute(
        f"SELECT {_COLUMNS} FROM approval_requests WHERE request_id = ?",
        (request_id,),
    ).fetchone()
    if row is None:
        return None
    return _approval(row)


def insert_posting(
    connection: sqlite3.Connection,
    request_id: str,
    correlation_id: str,
    system_source: str,
    callback_url: str,
    title: str,
    details: str | None,
    expires_at: str,
    created_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO approval_requests (
            request_id, correlation_id, system_source, callback_url, title, details,
            status, expires_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'posting', ?, ?)
        """,
        (
            request_id,
            correlation_id,
            system_source,
            callback_url,
            title,
            details,
            expires_at,
            created_at,
        ),
    )


def redrive(
    connection: sqlite3.Connection,
    request_id: str,
    system_source: str,
    callback_url: str,
    title: str,
    details: str | None,
    expires_at: str,
    created_at: str,
) -> int:
    cursor = connection.execute(
        """
        UPDATE approval_requests
        SET system_source = ?, callback_url = ?, title = ?, details = ?, expires_at = ?,
            created_at = ?, status = 'posting', slack_channel_id = NULL, slack_message_ts = NULL,
            decided_by = NULL, decided_at = NULL, callback_state = NULL,
            callback_delivered_at = NULL, callback_error_log = NULL, card_updated_at = NULL
        WHERE request_id = ? AND status = 'failed'
        """,
        (system_source, callback_url, title, details, expires_at, created_at, request_id),
    )
    return cursor.rowcount


def mark_pending(
    connection: sqlite3.Connection,
    request_id: str,
    slack_channel_id: str,
    slack_message_ts: str,
    card_updated_at: str,
) -> int:
    cursor = connection.execute(
        """
        UPDATE approval_requests
        SET status = 'pending', slack_channel_id = ?, slack_message_ts = ?, card_updated_at = ?
        WHERE request_id = ? AND status = 'posting'
        """,
        (slack_channel_id, slack_message_ts, card_updated_at, request_id),
    )
    return cursor.rowcount


def mark_failed(connection: sqlite3.Connection, request_id: str) -> int:
    cursor = connection.execute(
        """
        UPDATE approval_requests
        SET status = 'failed', slack_message_ts = NULL
        WHERE request_id = ? AND status = 'posting'
        """,
        (request_id,),
    )
    return cursor.rowcount


def decide(
    connection: sqlite3.Connection,
    request_id: str,
    new_status: str,
    slack_channel_id: str | None,
    slack_message_ts: str | None,
    decided_by: str | None,
    decided_at: str,
) -> int:
    cursor = connection.execute(
        """
        UPDATE approval_requests
        SET status = ?, slack_channel_id = ?, slack_message_ts = ?, decided_by = ?,
            decided_at = ?, callback_state = 'pending', callback_delivered_at = NULL,
            callback_error_log = NULL, card_updated_at = NULL
        WHERE request_id = ? AND status IN ('pending', 'posting', 'failed')
        """,
        (new_status, slack_channel_id, slack_message_ts, decided_by, decided_at, request_id),
    )
    return cursor.rowcount


def expire_pending(connection: sqlite3.Connection, now: str) -> list[ApprovalRow]:
    rows = connection.execute(
        f"""
        SELECT {_COLUMNS} FROM approval_requests
        WHERE status = 'pending' AND expires_at < ?
        """,
        (now,),
    ).fetchall()
    changed: list[ApprovalRow] = []
    for row in rows:
        current = _approval(row)
        cursor = connection.execute(
            """
            UPDATE approval_requests
            SET status = 'expired', decided_by = NULL, decided_at = ?, callback_state = 'pending',
                callback_delivered_at = NULL, callback_error_log = NULL, card_updated_at = NULL
            WHERE request_id = ? AND status = 'pending' AND expires_at < ?
            """,
            (now, current["request_id"], now),
        )
        if cursor.rowcount == 1:
            current["status"] = "expired"
            current["decided_by"] = None
            current["decided_at"] = now
            current["callback_state"] = "pending"
            current["callback_delivered_at"] = None
            current["callback_error_log"] = None
            current["card_updated_at"] = None
            changed.append(current)
    return changed


def abandoned_posting(connection: sqlite3.Connection, cutoff: str) -> list[ApprovalRow]:
    rows = connection.execute(
        f"""
        SELECT {_COLUMNS} FROM approval_requests
        WHERE status = 'posting' AND created_at < ?
        """,
        (cutoff,),
    ).fetchall()
    return [_approval(row) for row in rows]


def pending_callbacks(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        """
        SELECT request_id FROM approval_requests
        WHERE callback_state = 'pending'
        """
    ).fetchall()
    return [_text(row, "request_id") for row in rows]


def cards_to_repair(connection: sqlite3.Connection) -> list[ApprovalRow]:
    rows = connection.execute(
        f"""
        SELECT {_COLUMNS} FROM approval_requests
        WHERE status IN ('approved', 'rejected', 'expired')
          AND slack_message_ts IS NOT NULL
          AND card_updated_at IS NULL
        """
    ).fetchall()
    return [_approval(row) for row in rows]


def set_card_updated(connection: sqlite3.Connection, request_id: str, card_updated_at: str) -> None:
    connection.execute(
        "UPDATE approval_requests SET card_updated_at = ? WHERE request_id = ?",
        (card_updated_at, request_id),
    )


def mark_callback_delivered(
    connection: sqlite3.Connection, request_id: str, delivered_at: str
) -> None:
    connection.execute(
        """
        UPDATE approval_requests
        SET callback_state = 'delivered', callback_delivered_at = ?, callback_error_log = NULL
        WHERE request_id = ? AND callback_state = 'pending'
        """,
        (delivered_at, request_id),
    )


def mark_callback_exhausted(
    connection: sqlite3.Connection, request_id: str, error_log: str
) -> None:
    connection.execute(
        """
        UPDATE approval_requests
        SET callback_state = 'exhausted', callback_error_log = ?
        WHERE request_id = ? AND callback_state = 'pending'
        """,
        (error_log, request_id),
    )


def count_pending(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT COUNT(*) AS count_pending FROM approval_requests WHERE status = 'pending'"
    ).fetchone()
    if row is None:
        return 0
    value = row["count_pending"]
    if not isinstance(value, int):
        raise TypeError("count_pending")
    return value


def _approval(row: sqlite3.Row) -> ApprovalRow:
    return ApprovalRow(
        request_id=_text(row, "request_id"),
        correlation_id=_text(row, "correlation_id"),
        system_source=_text(row, "system_source"),
        callback_url=_text(row, "callback_url"),
        title=_text(row, "title"),
        details=_optional_text(row, "details"),
        status=_text(row, "status"),
        slack_channel_id=_optional_text(row, "slack_channel_id"),
        slack_message_ts=_optional_text(row, "slack_message_ts"),
        decided_by=_optional_text(row, "decided_by"),
        decided_at=_optional_text(row, "decided_at"),
        expires_at=_text(row, "expires_at"),
        created_at=_text(row, "created_at"),
        callback_state=_optional_text(row, "callback_state"),
        callback_delivered_at=_optional_text(row, "callback_delivered_at"),
        callback_error_log=_optional_text(row, "callback_error_log"),
        card_updated_at=_optional_text(row, "card_updated_at"),
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
