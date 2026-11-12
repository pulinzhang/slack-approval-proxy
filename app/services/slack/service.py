"""Slack Web API. Records each call through message trace before sending."""

import json
from dataclasses import dataclass

import httpx

from app.config import get_settings
from app.services.message_trace.service import begin_outbound, complete_call
from app.services.slack.cards import new_card, replaced_card, terminal_card

_API = "https://slack.com/api"


@dataclass(frozen=True)
class PostedCard:
    kind: str
    channel: str
    ts: str | None
    error: str | None


@dataclass(frozen=True)
class HistoryLookup:
    kind: str
    ts: str | None


def post_approval(
    correlation_id: str,
    request_id: str,
    title: str,
    system_source: str,
    expires_at: str,
    details: dict[str, str] | None,
) -> PostedCard:
    channel = get_settings().SLACK_CHANNEL_ID
    body = new_card(channel, request_id, title, system_source, expires_at, details)
    return _post(
        correlation_id,
        request_id,
        "slack_post_message",
        f"{_API}/chat.postMessage",
        body,
        channel,
    )


def update_terminal(
    correlation_id: str,
    request_id: str,
    channel: str,
    message_ts: str,
    title: str,
    system_source: str,
    expires_at: str,
    status: str,
    decided_by: str | None,
    decided_at: str | None,
) -> bool:
    body = terminal_card(
        channel,
        message_ts,
        title,
        request_id,
        system_source,
        expires_at,
        status,
        decided_by,
        decided_at,
    )
    result = _post(
        correlation_id,
        request_id,
        "slack_update_message",
        f"{_API}/chat.update",
        body,
        channel,
    )
    return result.kind == "accepted"


def update_replaced(correlation_id: str, request_id: str, channel: str, message_ts: str) -> None:
    body = replaced_card(channel, message_ts)
    _post(
        correlation_id,
        request_id,
        "slack_update_message",
        f"{_API}/chat.update",
        body,
        channel,
    )


def find_card(correlation_id: str, request_id: str) -> HistoryLookup:
    channel = get_settings().SLACK_CHANNEL_ID
    url = f"{_API}/conversations.history?channel={channel}&limit=100"
    exchange_id = begin_outbound(
        correlation_id,
        request_id,
        "slack",
        "slack_history",
        "GET",
        url.split("?", 1)[0],
        _headers(),
        None,
    )
    try:
        response = send("GET", url, _headers(), None)
    except httpx.TimeoutException as exc:
        complete_call(exchange_id, "timeout", None, None, None, "unknown", str(exc))
        return HistoryLookup("unknown", None)
    except httpx.TransportError as exc:
        complete_call(exchange_id, "transport_failed", None, None, None, "unknown", str(exc))
        return HistoryLookup("unknown", None)
    text = response.text
    outcome, status_name = _slack_outcome(response.status_code, text)
    complete_call(
        exchange_id,
        "completed" if response.status_code < 500 else "timeout",
        response.status_code,
        {"content-type": response.headers.get("content-type", "")},
        text,
        outcome,
        None,
    )
    if status_name != "accepted":
        return HistoryLookup("unknown", None)
    matched = _matching_ts(text, request_id)
    if matched is None:
        return HistoryLookup("miss", None)
    return HistoryLookup("hit", matched)


def send(method: str, url: str, headers: dict[str, str], body: str | None) -> httpx.Response:
    with httpx.Client(timeout=10.0) as client:
        if method == "GET":
            return client.get(url, headers=headers)
        return client.post(url, content=body, headers=headers)


def _post(
    correlation_id: str,
    request_id: str,
    operation: str,
    url: str,
    body: str,
    channel: str,
) -> PostedCard:
    exchange_id = begin_outbound(
        correlation_id,
        request_id,
        "slack",
        operation,
        "POST",
        url,
        _headers(),
        body,
    )
    try:
        response = send("POST", url, _headers(), body)
    except httpx.TimeoutException as exc:
        complete_call(exchange_id, "timeout", None, None, None, "unknown", str(exc))
        return PostedCard("unknown", channel, None, None)
    except httpx.TransportError as exc:
        complete_call(exchange_id, "transport_failed", None, None, None, "unknown", str(exc))
        return PostedCard("unknown", channel, None, None)
    text = response.text
    outcome, kind = _slack_outcome(response.status_code, text)
    error = _slack_error(text)
    ts = _ts(text) if kind == "accepted" else None
    if kind == "accepted" and operation == "slack_post_message" and ts is None:
        kind = "unknown"
        outcome = "unknown"
    complete_call(
        exchange_id,
        "completed" if response.status_code < 500 else "timeout",
        response.status_code,
        {"content-type": response.headers.get("content-type", "")},
        text,
        outcome,
        error if kind == "rejected" else None,
    )
    return PostedCard(kind, channel, ts, error)


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {get_settings().SLACK_BOT_TOKEN}",
        "Content-Type": "application/json; charset=utf-8",
    }


def _slack_outcome(status_code: int, body: str) -> tuple[str, str]:
    if status_code >= 500:
        return "unknown", "unknown"
    parsed = _object(body)
    if parsed is None:
        return "unknown", "unknown"
    ok = parsed.get("ok")
    if ok is False:
        return "failed", "rejected"
    if ok is True:
        return "succeeded", "accepted"
    return "unknown", "unknown"


def _slack_error(body: str) -> str | None:
    parsed = _object(body)
    if parsed is None:
        return None
    error = parsed.get("error")
    return error if isinstance(error, str) else None


def _ts(body: str) -> str | None:
    parsed = _object(body)
    if parsed is None:
        return None
    ts = parsed.get("ts")
    return ts if isinstance(ts, str) and ts else None


def _matching_ts(body: str, request_id: str) -> str | None:
    parsed = _object(body)
    if parsed is None:
        return None
    messages = parsed.get("messages")
    if not isinstance(messages, list):
        return None
    for item in messages:
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata")
        if not isinstance(metadata, dict):
            continue
        payload = metadata.get("event_payload")
        if not isinstance(payload, dict) or payload.get("request_id") != request_id:
            continue
        ts = item.get("ts")
        if isinstance(ts, str):
            return ts
    return None


def _object(body: str) -> dict[object, object] | None:
    try:
        parsed: object = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed
