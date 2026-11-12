"""Create, reconcile, or re-drive one approval."""

import json
from dataclasses import dataclass
from uuid import uuid4

from app.common.clock import format_utc, parse_utc, shift_minutes, utc_now
from app.common.locks import release, try_acquire
from app.database import read_connection, transaction
from app.exceptions.base import ConflictError, InternalError, SlackAPIError
from app.models.approval.row import ApprovalRow
from app.repositories.approval import repository as approval_repo
from app.schemas.dto.approval import CreateApprovalBody
from app.schemas.vo.approval import AlreadyDecidedApproval, CreatedApproval
from app.services.approval.callback.runner import schedule_callback
from app.services.message_trace.service import (
    audit_change,
    begin_inbound,
    complete_call,
    proxy_outcome,
)
from app.services.slack.service import find_card, post_approval, update_terminal

_UNKNOWN = "Slack outcome unknown; retry the same request_id"
_ACTIVE = "An active approval request with this ID already exists"
_IN_PROGRESS = "A create for this ID is still in progress"
_TERMINAL = {"approved", "rejected", "expired"}


@dataclass
class CreateContext:
    command: CreateApprovalBody
    raw_body: str
    headers: dict[str, str]
    correlation_id: str
    exchange_id: str
    request_id: str
    mode: str


@dataclass
class CreateOutcome:
    kind: str
    row: ApprovalRow


class CreateApprovalOrchestrator:
    def execute(
        self, command: CreateApprovalBody, raw_body: str, headers: dict[str, str]
    ) -> CreatedApproval | AlreadyDecidedApproval:
        ctx = prepare_create(command, raw_body, headers)
        try:
            outcome = run_create(ctx)
            return persist_create(ctx, outcome)
        finally:
            release(ctx.request_id)


def prepare_create(
    command: CreateApprovalBody, raw_body: str, headers: dict[str, str]
) -> CreateContext:
    if not try_acquire(command.request_id):
        _open_exchange(command, raw_body, headers, str(uuid4()))
        raise ConflictError(_IN_PROGRESS, command.request_id)
    try:
        return _prepare_locked(command, raw_body, headers)
    except Exception:
        release(command.request_id)
        raise


def run_create(ctx: CreateContext) -> CreateOutcome:
    if ctx.mode == "already":
        return CreateOutcome("already", _load(ctx.request_id))
    if ctx.mode == "reconcile":
        return _reconcile(ctx, _load(ctx.request_id))
    return _post_new_card(ctx)


def persist_create(
    ctx: CreateContext, outcome: CreateOutcome
) -> CreatedApproval | AlreadyDecidedApproval:
    if outcome.kind == "already":
        model: CreatedApproval | AlreadyDecidedApproval = _already(outcome.row)
    else:
        model = CreatedApproval(
            result="created",
            request_id=outcome.row["request_id"],
            correlation_id=outcome.row["correlation_id"],
            status=outcome.row["status"],
            expires_at=outcome.row["expires_at"],
        )
    body = model.model_dump_json()
    complete_call(
        ctx.exchange_id,
        "completed",
        200,
        {"content-type": "application/json"},
        body,
        proxy_outcome(body),
        None,
    )
    return model


def _prepare_locked(
    command: CreateApprovalBody, raw_body: str, headers: dict[str, str]
) -> CreateContext:
    existing = _peek(command.request_id)
    if existing is None:
        correlation_id = str(uuid4())
        exchange_id = _open_exchange(command, raw_body, headers, correlation_id)
        _insert_posting(command, correlation_id)
        return CreateContext(
            command, raw_body, headers, correlation_id, exchange_id, command.request_id, "post"
        )
    exchange_id = _open_exchange(command, raw_body, headers, existing["correlation_id"])
    ctx = CreateContext(
        command,
        raw_body,
        headers,
        existing["correlation_id"],
        exchange_id,
        command.request_id,
        "post",
    )
    if existing["status"] == "pending":
        raise ConflictError(_ACTIVE, command.request_id)
    if existing["status"] in _TERMINAL:
        ctx.mode = "already"
        return ctx
    if existing["status"] == "posting":
        ctx.mode = "reconcile"
        return ctx
    ctx.mode = _redrive(ctx)
    return ctx


def _reconcile(ctx: CreateContext, row: ApprovalRow) -> CreateOutcome:
    found = find_card(row["correlation_id"], row["request_id"])
    if found.kind == "unknown":
        raise SlackAPIError(_UNKNOWN)
    if found.kind == "hit" and found.ts is not None:
        _apply_visible_card(ctx, row, found.ts)
        return CreateOutcome("created", _load(ctx.request_id))
    _change_status(ctx, "posting", "failed", "reconcile_miss")
    followed = _redrive(ctx)
    if followed == "post":
        return _post_new_card(ctx)
    if followed == "already":
        return CreateOutcome("already", _load(ctx.request_id))
    raise SlackAPIError(_UNKNOWN)


def _post_new_card(ctx: CreateContext) -> CreateOutcome:
    command = ctx.command
    posted = post_approval(
        ctx.correlation_id,
        command.request_id,
        command.title,
        command.system_source,
        _load(ctx.request_id)["expires_at"],
        command.details,
    )
    if posted.kind == "unknown":
        raise SlackAPIError(_UNKNOWN)
    if posted.kind == "rejected":
        _change_status(ctx, "posting", "failed", "slack_post_failed")
        raise SlackAPIError(f"Failed to post message to Slack: {posted.error or 'unknown_error'}")
    _store_pending(ctx, posted.channel, posted.ts or "")
    row = _load(ctx.request_id)
    if utc_now() > parse_utc(row["expires_at"]):
        _expire_pending_card(ctx, row)
        row = _load(ctx.request_id)
    return CreateOutcome("created", row)


def _apply_visible_card(ctx: CreateContext, row: ApprovalRow, ts: str) -> None:
    channel = row["slack_channel_id"] or get_channel()
    if utc_now() > parse_utc(row["expires_at"]):
        _expire_found(ctx, row, channel, ts)
        return
    _store_pending(ctx, channel, ts)


def _expire_found(ctx: CreateContext, row: ApprovalRow, channel: str, ts: str) -> None:
    decided_at = format_utc(utc_now())
    changed = _decide(ctx, row, "expired", channel, ts, None, decided_at, "expire", "system")
    if changed:
        _refresh_card(ctx, _load(ctx.request_id))
        schedule_callback(ctx.request_id)


def _expire_pending_card(ctx: CreateContext, row: ApprovalRow) -> None:
    decided_at = format_utc(utc_now())
    channel = row["slack_channel_id"] or ""
    ts = row["slack_message_ts"] or ""
    changed = _decide(ctx, row, "expired", channel, ts, None, decided_at, "expire", "system")
    if changed:
        _refresh_card(ctx, _load(ctx.request_id))
        schedule_callback(ctx.request_id)


def _store_pending(ctx: CreateContext, channel: str, ts: str) -> None:
    stamped = format_utc(utc_now())
    for _ in range(3):
        try:
            with transaction() as connection:
                changed = approval_repo.mark_pending(
                    connection, ctx.request_id, channel, ts, stamped
                )
                if changed == 1:
                    audit_change(
                        connection,
                        ctx.correlation_id,
                        ctx.request_id,
                        "posting",
                        "pending",
                        "system",
                        "slack_posted",
                    )
            if _load(ctx.request_id)["status"] == "pending":
                return
            raise SlackAPIError(_UNKNOWN)
        except SlackAPIError:
            raise
        except Exception as exc:
            if _is_database_error(exc):
                continue
            raise
    raise SlackAPIError(_UNKNOWN)


def _redrive(ctx: CreateContext) -> str:
    command = ctx.command
    now = utc_now()
    created_at = format_utc(now)
    expires_at = format_utc(shift_minutes(now, command.timeout_minutes))
    details = _details_text(command.details)
    with transaction() as connection:
        changed = approval_repo.redrive(
            connection,
            command.request_id,
            command.system_source,
            command.callback_url,
            command.title,
            details,
            expires_at,
            created_at,
        )
        if changed == 0:
            return _mode_after_miss(ctx)
        audit_change(
            connection, ctx.correlation_id, ctx.request_id, "failed", "posting", "system", "redrive"
        )
    return "post"


def _mode_after_miss(ctx: CreateContext) -> str:
    current = _load(ctx.request_id)
    if current["status"] == "pending":
        raise ConflictError(_ACTIVE, ctx.request_id)
    if current["status"] in _TERMINAL:
        return "already"
    if current["status"] == "posting":
        return "reconcile"
    raise SlackAPIError(_UNKNOWN)


def _insert_posting(command: CreateApprovalBody, correlation_id: str) -> None:
    now = utc_now()
    with transaction() as connection:
        approval_repo.insert_posting(
            connection,
            command.request_id,
            correlation_id,
            command.system_source,
            command.callback_url,
            command.title,
            _details_text(command.details),
            format_utc(shift_minutes(now, command.timeout_minutes)),
            format_utc(now),
        )
        audit_change(
            connection, correlation_id, command.request_id, None, "posting", "system", "create"
        )


def _decide(
    ctx: CreateContext,
    row: ApprovalRow,
    new_status: str,
    channel: str,
    ts: str,
    decided_by: str | None,
    decided_at: str,
    reason: str,
    actor: str,
) -> bool:
    with transaction() as connection:
        changed = approval_repo.decide(
            connection, ctx.request_id, new_status, channel, ts, decided_by, decided_at
        )
        if changed != 1:
            return False
        audit_change(
            connection, ctx.correlation_id, ctx.request_id, row["status"], new_status, actor, reason
        )
    return True


def _change_status(ctx: CreateContext, from_status: str, to_status: str, reason: str) -> None:
    with transaction() as connection:
        changed = approval_repo.mark_failed(connection, ctx.request_id)
        if changed != 1:
            return
        audit_change(
            connection, ctx.correlation_id, ctx.request_id, from_status, to_status, "system", reason
        )


def _refresh_card(ctx: CreateContext, row: ApprovalRow) -> None:
    channel = row["slack_channel_id"]
    ts = row["slack_message_ts"]
    if channel is None or ts is None:
        return
    update_terminal(
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


def _open_exchange(
    command: CreateApprovalBody, raw_body: str, headers: dict[str, str], correlation_id: str
) -> str:
    return begin_inbound(
        correlation_id,
        command.request_id,
        command.system_source,
        "create_approval",
        "POST",
        "/api/v1/approvals",
        headers,
        raw_body,
    )


def _already(row: ApprovalRow) -> AlreadyDecidedApproval:
    return AlreadyDecidedApproval(
        result="already_decided",
        request_id=row["request_id"],
        correlation_id=row["correlation_id"],
        system_source=row["system_source"],
        status=row["status"],
        decided_by=row["decided_by"],
        decided_at=row["decided_at"],
        expires_at=row["expires_at"],
        created_at=row["created_at"],
        callback_state=row["callback_state"],
        callback_delivered_at=row["callback_delivered_at"],
        callback_error_log=row["callback_error_log"],
    )


def _load(request_id: str) -> ApprovalRow:
    row = _peek(request_id)
    if row is None:
        raise InternalError()
    return row


def _peek(request_id: str) -> ApprovalRow | None:
    with read_connection() as connection:
        return approval_repo.get(connection, request_id)


def _details_text(details: dict[str, str] | None) -> str | None:
    if details is None:
        return None
    return json.dumps(details, ensure_ascii=False, separators=(",", ":"))


def _is_database_error(exc: Exception) -> bool:
    return exc.__class__.__module__.startswith("sqlite3")


def get_channel() -> str:
    from app.config import get_settings

    return get_settings().SLACK_CHANNEL_ID
