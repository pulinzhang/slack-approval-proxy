"""Message-exchange reads for the control tower."""

from fastapi import APIRouter, Depends, Query

from app.common.auth import require_api_key
from app.schemas.vo.trace import ExchangeDetail, ExchangeList, ExchangeSummaryReport
from app.services.message_trace.service import ExchangeQuery, get_message, list_messages, summarize

router = APIRouter(prefix="/api/v1/message-exchanges", tags=["message-exchanges"])


@router.get("")
def list_exchanges(
    request_id: str | None = None,
    correlation_id: str | None = None,
    direction: str | None = None,
    exchange_status: str | None = None,
    business_outcome: str | None = None,
    operation: str | None = None,
    page: int = Query(default=1),
    size: int = Query(default=20),
    include_operator_reads: bool = False,
    _: None = Depends(require_api_key),
) -> ExchangeList:
    return list_messages(
        ExchangeQuery(
            request_id,
            correlation_id,
            direction,
            exchange_status,
            business_outcome,
            operation,
            page,
            size,
            include_operator_reads,
        )
    )


@router.get("/summary")
def read_summary(
    include_operator_reads: bool = False,
    _: None = Depends(require_api_key),
) -> ExchangeSummaryReport:
    return summarize(include_operator_reads)


@router.get("/{exchange_id}")
def read_exchange(exchange_id: str, _: None = Depends(require_api_key)) -> ExchangeDetail:
    return get_message(exchange_id)
