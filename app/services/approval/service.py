"""Facade. Conductors are invoked only through execute."""

from app.schemas.dto.approval import CreateApprovalBody
from app.schemas.vo.approval import AlreadyDecidedApproval, ApprovalStatus, CreatedApproval
from app.schemas.vo.trace import ApprovalTrace
from app.services.approval.create.orchestrator import CreateApprovalOrchestrator
from app.services.approval.decision.orchestrator import DecisionOrchestrator
from app.services.approval.query import read_approval, read_approval_trace
from app.services.slack.payload import SlackInteraction


class ApprovalService:
    def create_approval(
        self, command: CreateApprovalBody, raw_body: str, headers: dict[str, str]
    ) -> CreatedApproval | AlreadyDecidedApproval:
        return CreateApprovalOrchestrator().execute(command, raw_body, headers)

    def get_approval(self, request_id: str, headers: dict[str, str]) -> ApprovalStatus:
        return read_approval(request_id, headers)

    def read_trace(self, request_id: str) -> ApprovalTrace:
        return read_approval_trace(request_id)

    def apply_decision(
        self, interaction: SlackInteraction, raw_body: str, headers: dict[str, str]
    ) -> None:
        DecisionOrchestrator().execute(interaction, raw_body, headers)
