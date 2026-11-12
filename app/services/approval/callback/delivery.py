"""Send one callback wave. Each attempt is its own exchange."""

import json
from urllib.parse import urlsplit

import httpx

from app.models.approval.row import ApprovalRow
from app.services.message_trace.service import begin_outbound, complete_call, external_outcome
from app.services.slack.service import send


def deliver(row: ApprovalRow, attempt: int) -> tuple[str, str]:
    """Return (`delivered`, ``) or (`failed`, error log). Raise MessageTraceError before send."""
    url = row["callback_url"]
    body = json.dumps(
        {
            "request_id": row["request_id"],
            "status": row["status"],
            "decided_by": row["decided_by"],
            "decided_at": row["decided_at"],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    headers = {"Content-Type": "application/json"}
    exchange_id = begin_outbound(
        row["correlation_id"],
        row["request_id"],
        urlsplit(url).netloc or url,
        "callback",
        "POST",
        url,
        headers,
        body,
        attempt,
    )
    try:
        response = send("POST", url, headers, body)
    except httpx.TimeoutException as exc:
        complete_call(exchange_id, "timeout", None, None, None, "unknown", str(exc))
        return "failed", "transport: timeout"
    except httpx.TransportError as exc:
        complete_call(exchange_id, "transport_failed", None, None, None, "unknown", str(exc))
        return "failed", f"transport: {exc}"
    text = response.text
    outcome = external_outcome(response.status_code, text, False)
    complete_call(
        exchange_id,
        "completed",
        response.status_code,
        {"content-type": response.headers.get("content-type", "")},
        text,
        outcome,
        None if outcome == "succeeded" else text[:200],
    )
    if outcome == "succeeded":
        return "delivered", ""
    return "failed", f"HTTP {response.status_code}: {text[:200]}"
