"""Approval reads that are not one of the four conductors."""

from uuid import uuid4

from app.database import read_connection
from app.exceptions.base import NotFoundError
from app.repositories.approval import repository as approval_repo
from app.schemas.vo.approval import ApprovalStatus
from app.schemas.vo.trace import ApprovalTrace
from app.services.message_trace.service import begin_inbound, complete_call, read_chain


def read_approval(request_id: str, headers: dict[str, str]) -> ApprovalStatus:
    with read_connection() as connection:
        row = approval_repo.get(connection, request_id)
    source = row["system_source"] if row is not None else "external"
    correlation_id = row["correlation_id"] if row is not None else str(uuid4())
    exchange_id = begin_inbound(
        correlation_id,
        request_id,
        source,
        "get_approval",
        "GET",
        f"/api/v1/approvals/{request_id}",
        headers,
        None,
    )
    if row is None:
        complete_call(
            exchange_id,
            "completed",
            404,
            {"content-type": "application/json"},
            '{"error":"NotFound","message":"Approval request not found"}',
            "failed",
            None,
        )
        raise NotFoundError()
    status = ApprovalStatus(
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
    complete_call(
        exchange_id,
        "completed",
        200,
        {"content-type": "application/json"},
        status.model_dump_json(),
        "succeeded",
        None,
    )
    return status


def read_approval_trace(request_id: str) -> ApprovalTrace:
    with read_connection() as connection:
        row = approval_repo.get(connection, request_id)
    correlation_id = row["correlation_id"] if row is not None else None
    return read_chain(request_id, correlation_id)
