"""Apply one Slack click: decide, repair the card, or ignore it."""

from dataclasses import dataclass

from app.common.clock import format_utc, parse_utc, utc_now
from app.database import read_connection, transaction
from app.exceptions.base import NotFoundError
from app.models.approval.row import ApprovalRow
from app.repositories.approval import repository as approval_repo
from app.services.approval.callback.runner import schedule_callback
from app.services.message_trace.service import audit_change, begin_inbound, complete_call
from app.services.slack.payload import SlackInteraction
from app.services.slack.service import update_replaced, update_terminal

_DECISIONS = {"approve_request", "reject_request"}
_TERMINAL = {"approved", "rejected", "expired"}


@dataclass
class DecisionContext:
    interaction: SlackInteraction
    exchange_id: str | None
    mode: str
    row: ApprovalRow | None
    winner: bool


@dataclass
class DecisionOutcome:
    card_updated: bool


class DecisionOrchestrator:
    def execute(
        self, interaction: SlackInteraction, raw_body: str, headers: dict[str, str]
    ) -> None:
        ctx = prepare_decision(interaction, raw_body, headers)
        outcome = run_decision(ctx)
        persist_decision(ctx, outcome)


def prepare_decision(
    interaction: SlackInteraction, raw_body: str, headers: dict[str, str]
) -> DecisionContext:
    if interaction.action_id not in _DECISIONS:
        exchange_id = _open(interaction, raw_body, headers, None)
        return DecisionContext(interaction, exchange_id, "ignore", None, False)
    if interaction.request_id is None:
        _open(interaction, raw_body, headers, None)
        raise NotFoundError()
    with read_connection() as connection:
        row = approval_repo.get(connection, interaction.request_id)
    exchange_id = _open(interaction, raw_body, headers, row["correlation_id"] if row else None)
    if row is None:
        raise NotFoundError()
    if _is_stale(row, interaction):
        return DecisionContext(interaction, exchange_id, "stale", row, False)
    if row["status"] in _TERMINAL:
        return DecisionContext(interaction, exchange_id, "repair", row, False)
    winner = _claim(row, interaction)
    current = _reload(interaction.request_id)
    if winner:
        return DecisionContext(interaction, exchange_id, "winner", current, True)
    return DecisionContext(interaction, exchange_id, "repair", current, False)


def run_decision(ctx: DecisionContext) -> DecisionOutcome:
    row = ctx.row
    interaction = ctx.interaction
    if ctx.mode == "ignore" or row is None:
        return DecisionOutcome(False)
    channel = interaction.channel_id or row["slack_channel_id"] or ""
    if ctx.mode == "stale":
        message_ts = interaction.message_ts or ""
        update_replaced(row["correlation_id"], row["request_id"], channel, message_ts)
        return DecisionOutcome(False)
    message_ts = row["slack_message_ts"] or interaction.message_ts or ""
    updated = update_terminal(
        row["correlation_id"],
        row["request_id"],
        channel,
        message_ts,
        row["title"],
        row["system_source"],
        row["expires_at"],
        row["status"],
        row["decided_by"],
        row["decided_at"],
    )
    return DecisionOutcome(updated)


def persist_decision(ctx: DecisionContext, outcome: DecisionOutcome) -> None:
    row = ctx.row
    if outcome.card_updated and row is not None and ctx.mode in {"winner", "repair"}:
        with transaction() as connection:
            approval_repo.set_card_updated(connection, row["request_id"], format_utc(utc_now()))
    if ctx.winner and row is not None:
        schedule_callback(row["request_id"])
    if ctx.exchange_id is not None:
        complete_call(ctx.exchange_id, "completed", 200, {}, "", "succeeded", None)


def _claim(row: ApprovalRow, interaction: SlackInteraction) -> bool:
    past_due = utc_now() > parse_utc(row["expires_at"])
    decided_at = format_utc(utc_now())
    if past_due:
        new_status = "expired"
        decided_by = None
        actor = interaction.user_id or "system"
        reason = "expire"
    elif interaction.action_id == "approve_request":
        new_status = "approved"
        decided_by = interaction.user_id
        reason = "approve"
        actor = interaction.user_id or "system"
    else:
        new_status = "rejected"
        decided_by = interaction.user_id
        reason = "reject"
        actor = interaction.user_id or "system"
    channel = interaction.channel_id or row["slack_channel_id"]
    ts = interaction.message_ts or row["slack_message_ts"]
    with transaction() as connection:
        changed = approval_repo.decide(
            connection, row["request_id"], new_status, channel, ts, decided_by, decided_at
        )
        if changed != 1:
            return False
        audit_change(
            connection,
            row["correlation_id"],
            row["request_id"],
            row["status"],
            new_status,
            actor,
            reason,
        )
    return True


def _open(
    interaction: SlackInteraction,
    raw_body: str,
    headers: dict[str, str],
    correlation_id: str | None,
) -> str:
    from uuid import uuid4

    return begin_inbound(
        correlation_id or str(uuid4()),
        interaction.request_id,
        "slack",
        "slack_interactive",
        "POST",
        "/api/v1/slack/interactive",
        headers,
        raw_body,
    )


def _is_stale(row: ApprovalRow, interaction: SlackInteraction) -> bool:
    stored = row["slack_message_ts"]
    clicked = interaction.message_ts
    return stored is not None and clicked is not None and stored != clicked


def _reload(request_id: str | None) -> ApprovalRow | None:
    if request_id is None:
        return None
    with read_connection() as connection:
        return approval_repo.get(connection, request_id)
