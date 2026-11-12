"""Approval HTTP bodies."""

from pydantic import BaseModel, ConfigDict


class CreatedApproval(BaseModel):
    model_config = ConfigDict()

    result: str
    request_id: str
    correlation_id: str
    status: str
    expires_at: str


class AlreadyDecidedApproval(BaseModel):
    model_config = ConfigDict()

    result: str
    request_id: str
    correlation_id: str
    system_source: str
    status: str
    decided_by: str | None
    decided_at: str | None
    expires_at: str
    created_at: str
    callback_state: str | None
    callback_delivered_at: str | None
    callback_error_log: str | None


class ApprovalStatus(BaseModel):
    model_config = ConfigDict()

    request_id: str
    correlation_id: str
    system_source: str
    status: str
    decided_by: str | None
    decided_at: str | None
    expires_at: str
    created_at: str
    callback_state: str | None
    callback_delivered_at: str | None
    callback_error_log: str | None
