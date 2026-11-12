"""Approval routes."""

from fastapi import APIRouter, Depends, Request

from app.common.auth import header_map, require_api_key
from app.schemas.dto.approval import CreateApprovalBody
from app.schemas.vo.approval import AlreadyDecidedApproval, ApprovalStatus, CreatedApproval
from app.schemas.vo.trace import ApprovalTrace
from app.services.approval.service import ApprovalService

router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"])
_service = ApprovalService()


@router.post("")
async def create_approval(
    request: Request,
    body: CreateApprovalBody,
    _: None = Depends(require_api_key),
) -> CreatedApproval | AlreadyDecidedApproval:
    raw = (await request.body()).decode("utf-8")
    return _service.create_approval(body, raw, header_map(list(request.headers.items())))


@router.get("/{request_id}/trace")
def read_trace(request_id: str, _: None = Depends(require_api_key)) -> ApprovalTrace:
    return _service.read_trace(request_id)


@router.get("/{request_id}")
def get_approval(
    request_id: str, request: Request, _: None = Depends(require_api_key)
) -> ApprovalStatus:
    return _service.get_approval(request_id, header_map(list(request.headers.items())))
