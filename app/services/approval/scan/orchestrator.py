"""Minute scan in the design's order."""

import logging
from dataclasses import dataclass

from app.common.clock import format_utc, parse_utc, shift_days, shift_seconds, utc_now
from app.common.locks import callback_is_running, is_held
from app.database import read_connection, transaction
from app.models.approval.row import ApprovalRow
from app.repositories.approval import repository as approval_repo
from app.services.approval.callback.runner import schedule_callback
from app.services.message_trace.service import audit_change, purge_expired, timeout_open_exchanges
from app.services.slack.service import find_card, update_terminal

logger = logging.getLogger(__name__)


@dataclass
class ScanClock:
    now: str


class ScanOrchestrator:
    def execute(self) -> None:
        ctx = prepare_scan()
        run_scan(ctx)
        persist_scan(ctx)


def prepare_scan() -> ScanClock:
    return ScanClock(format_utc(utc_now()))


def run_scan(ctx: ScanClock) -> None:
    _expire(ctx.now)
    _finish_callbacks()
    _repair_cards()
    _reconcile_posts(ctx.now)
    _close_exchanges(ctx.now)
    _purge(ctx.now)


def persist_scan(ctx: ScanClock) -> None:
    del ctx


def _expire(now: str) -> None:
    with transaction() as connection:
        changed = approval_repo.expire_pending(connection, now)
        for row in changed:
            audit_change(
                connection,
                row["correlation_id"],
                row["request_id"],
                "pending",
                "expired",
                "system",
                "expire",
            )
    for row in changed:
        _refresh(row)
        schedule_callback(row["request_id"])


def _finish_callbacks() -> None:
    with read_connection() as connection:
        request_ids = approval_repo.pending_callbacks(connection)
    for request_id in request_ids:
        if not callback_is_running(request_id):
            schedule_callback(request_id)


def _repair_cards() -> None:
    with read_connection() as connection:
        rows = approval_repo.cards_to_repair(connection)
    for row in rows:
        if _refresh(row):
            with transaction() as connection:
                approval_repo.set_card_updated(connection, row["request_id"], format_utc(utc_now()))


def _reconcile_posts(now: str) -> None:
    cutoff = format_utc(shift_seconds(parse_utc(now), -60))
    with read_connection() as connection:
        rows = approval_repo.abandoned_posting(connection, cutoff)
    for row in rows:
        if is_held(row["request_id"]):
            continue
        found = find_card(row["correlation_id"], row["request_id"])
        if found.kind == "unknown":
            continue
        if found.kind == "hit" and found.ts is not None:
            _claim_found(row, found.ts, now)
            continue
        _mark_miss(row)


def _close_exchanges(now: str) -> None:
    cutoff = format_utc(shift_seconds(parse_utc(now), -60))
    timeout_open_exchanges(cutoff)


def _purge(now: str) -> None:
    try:
        moment = parse_utc(now)
        purge_expired(
            format_utc(shift_days(moment, -30)),
            format_utc(shift_days(moment, -365)),
        )
    except Exception:
        logger.error("message_trace_write_failed")


def _claim_found(row: ApprovalRow, ts: str, now: str) -> None:
    channel = row["slack_channel_id"] or ""
    from app.config import get_settings

    if channel == "":
        channel = get_settings().SLACK_CHANNEL_ID
    if parse_utc(now) > parse_utc(row["expires_at"]):
        changed = 0
        with transaction() as connection:
            changed = approval_repo.decide(
                connection, row["request_id"], "expired", channel, ts, None, now
            )
            if changed == 1:
                audit_change(
                    connection,
                    row["correlation_id"],
                    row["request_id"],
                    "posting",
                    "expired",
                    "system",
                    "expire",
                )
        if changed == 1:
            current = _reload(row["request_id"])
            if current is not None:
                _refresh(current)
            schedule_callback(row["request_id"])
        return
    stamped = format_utc(utc_now())
    with transaction() as connection:
        changed = approval_repo.mark_pending(connection, row["request_id"], channel, ts, stamped)
        if changed == 1:
            audit_change(
                connection,
                row["correlation_id"],
                row["request_id"],
                "posting",
                "pending",
                "system",
                "reconcile",
            )


def _mark_miss(row: ApprovalRow) -> None:
    with transaction() as connection:
        changed = approval_repo.mark_failed(connection, row["request_id"])
        if changed == 1:
            audit_change(
                connection,
                row["correlation_id"],
                row["request_id"],
                "posting",
                "failed",
                "system",
                "reconcile_miss",
            )


def _refresh(row: ApprovalRow) -> bool:
    channel = row["slack_channel_id"]
    ts = row["slack_message_ts"]
    if channel is None or ts is None:
        return False
    return update_terminal(
        row["correlation_id"],
        row["request_id"],
        channel,
        ts,
        row["title"],
        row["system_source"],
        row["expires_at"],
        row["status"],
        row["decided_by"],
        row["decided_at"],
    )


def _reload(request_id: str) -> ApprovalRow | None:
    with read_connection() as connection:
        return approval_repo.get(connection, request_id)
