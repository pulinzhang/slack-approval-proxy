"""One callback wave: send, then retry after 2s, 5s, and 10s."""

from dataclasses import dataclass

from app.common.clock import format_utc, utc_now
from app.database import read_connection, transaction
from app.exceptions.base import MessageTraceError
from app.models.approval.row import ApprovalRow
from app.repositories.approval import repository as approval_repo
from app.services.approval.callback.delivery import deliver
from app.services.approval.callback.runner import pause

_DELAYS = (0, 2, 5, 10)
_TERMINAL = {"approved", "rejected", "expired"}


@dataclass
class CallbackContext:
    request_id: str
    row: ApprovalRow | None


@dataclass
class CallbackOutcome:
    kind: str
    error_log: str | None


class CallbackOrchestrator:
    def execute(self, request_id: str) -> None:
        ctx = prepare_callback(request_id)
        outcome = run_callback(ctx)
        persist_callback(ctx, outcome)


def prepare_callback(request_id: str) -> CallbackContext:
    with read_connection() as connection:
        row = approval_repo.get(connection, request_id)
    return CallbackContext(request_id, row)


def run_callback(ctx: CallbackContext) -> CallbackOutcome:
    row = ctx.row
    if row is None or row["callback_state"] != "pending" or row["status"] not in _TERMINAL:
        return CallbackOutcome("skip", None)
    error_log = ""
    for attempt, delay in enumerate(_DELAYS, start=1):
        if delay:
            pause(delay)
        try:
            result, error_log = deliver(row, attempt)
        except MessageTraceError:
            return CallbackOutcome("aborted", None)
        if result == "delivered":
            return CallbackOutcome("delivered", None)
    return CallbackOutcome("exhausted", error_log)


def persist_callback(ctx: CallbackContext, outcome: CallbackOutcome) -> None:
    if outcome.kind == "delivered":
        with transaction() as connection:
            approval_repo.mark_callback_delivered(connection, ctx.request_id, format_utc(utc_now()))
    elif outcome.kind == "exhausted" and outcome.error_log is not None:
        with transaction() as connection:
            approval_repo.mark_callback_exhausted(connection, ctx.request_id, outcome.error_log)
