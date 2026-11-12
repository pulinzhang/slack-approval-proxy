"""Slack interactive route."""

from fastapi import APIRouter, Request, Response

from app.common.auth import header_map
from app.services.approval.service import ApprovalService
from app.services.slack.payload import parse_interaction
from app.services.slack.signature import verify_signature

router = APIRouter(prefix="/api/v1/slack", tags=["slack"])
_service = ApprovalService()


@router.post("/interactive")
async def interactive(request: Request) -> Response:
    raw = await request.body()
    verify_signature(
        raw,
        request.headers.get("x-slack-request-timestamp"),
        request.headers.get("x-slack-signature"),
    )
    interaction = parse_interaction(raw)
    _service.apply_decision(
        interaction,
        raw.decode("utf-8"),
        header_map(list(request.headers.items())),
    )
    return Response(status_code=200)
