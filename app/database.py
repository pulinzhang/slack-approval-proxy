"""SQLite schema and short-lived connections. Repositories do not commit."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from app.config import database_file

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS approval_requests (
    request_id TEXT PRIMARY KEY,
    correlation_id TEXT NOT NULL,
    system_source TEXT NOT NULL,
    callback_url TEXT NOT NULL,
    title TEXT NOT NULL,
    details TEXT,
    status TEXT NOT NULL,
    slack_channel_id TEXT,
    slack_message_ts TEXT,
    decided_by TEXT,
    decided_at TEXT,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    callback_state TEXT,
    callback_delivered_at TEXT,
    callback_error_log TEXT,
    card_updated_at TEXT
);

CREATE TABLE IF NOT EXISTS message_exchanges (
    exchange_id TEXT PRIMARY KEY,
    correlation_id TEXT NOT NULL,
    request_id TEXT,
    direction TEXT NOT NULL,
    source_system TEXT NOT NULL,
    target_system TEXT NOT NULL,
    operation TEXT NOT NULL,
    http_method TEXT NOT NULL,
    url TEXT NOT NULL,
    request_headers TEXT NOT NULL,
    request_body TEXT,
    sent_at TEXT NOT NULL,
    exchange_status TEXT NOT NULL,
    http_status INTEGER,
    response_headers TEXT,
    response_body TEXT,
    received_at TEXT,
    duration_ms INTEGER,
    business_outcome TEXT,
    error_message TEXT,
    body_truncated INTEGER NOT NULL DEFAULT 0,
    attempt INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_message_exchanges_request_id
    ON message_exchanges (request_id);
CREATE INDEX IF NOT EXISTS idx_message_exchanges_correlation_id
    ON message_exchanges (correlation_id);

CREATE TABLE IF NOT EXISTS http_call_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exchange_id TEXT,
    correlation_id TEXT,
    request_id TEXT,
    direction TEXT NOT NULL,
    source_system TEXT NOT NULL,
    target_system TEXT NOT NULL,
    operation TEXT NOT NULL,
    http_method TEXT NOT NULL,
    url TEXT NOT NULL,
    http_status INTEGER,
    duration_ms INTEGER,
    error_message TEXT,
    called_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_http_call_logs_request_id ON http_call_logs (request_id);
CREATE INDEX IF NOT EXISTS idx_http_call_logs_called_at ON http_call_logs (called_at);

CREATE TABLE IF NOT EXISTS business_audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    correlation_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_business_audit_logs_request_id
    ON business_audit_logs (request_id);
"""


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(database_file(), timeout=5.0, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


@contextmanager
def read_connection() -> Iterator[sqlite3.Connection]:
    connection = connect()
    try:
        yield connection
    finally:
        connection.close()


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    connection = connect()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def create_tables() -> None:
    path = database_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA_SQL)
