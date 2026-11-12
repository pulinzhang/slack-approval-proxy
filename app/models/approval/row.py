"""approval_requests row."""

from typing import TypedDict


class ApprovalRow(TypedDict):
    request_id: str
    correlation_id: str
    system_source: str
    callback_url: str
    title: str
    details: str | None
    status: str
    slack_channel_id: str | None
    slack_message_ts: str | None
    decided_by: str | None
    decided_at: str | None
    expires_at: str
    created_at: str
    callback_state: str | None
    callback_delivered_at: str | None
    callback_error_log: str | None
    card_updated_at: str | None
