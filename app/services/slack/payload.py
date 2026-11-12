"""Parse a Slack interactive payload after the signature check."""

import json
from dataclasses import dataclass
from urllib.parse import parse_qs

from app.exceptions.base import InvalidPayloadError

_DECISIONS = {"approve_request", "reject_request"}


@dataclass(frozen=True)
class SlackInteraction:
    request_id: str | None
    action_id: str | None
    user_id: str | None
    message_ts: str | None
    channel_id: str | None


def parse_interaction(raw_body: bytes) -> SlackInteraction:
    try:
        text = raw_body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidPayloadError() from exc
    payload_values = parse_qs(text, keep_blank_values=True).get("payload", [])
    if not payload_values:
        raise InvalidPayloadError()
    try:
        parsed: object = json.loads(payload_values[0])
    except json.JSONDecodeError as exc:
        raise InvalidPayloadError() from exc
    if not isinstance(parsed, dict):
        raise InvalidPayloadError()
    action_id, request_id = _action(parsed)
    user_id = _user_id(parsed)
    if action_id in _DECISIONS and user_id is None:
        raise InvalidPayloadError()
    return SlackInteraction(
        request_id=request_id,
        action_id=action_id,
        user_id=user_id,
        message_ts=_message_ts(parsed),
        channel_id=_channel_id(parsed),
    )


def _action(payload: dict[object, object]) -> tuple[str | None, str | None]:
    actions = payload.get("actions")
    if not isinstance(actions, list) or not actions:
        return None, None
    first = actions[0]
    if not isinstance(first, dict):
        return None, None
    action_id = first.get("action_id")
    value = first.get("value")
    return (
        action_id if isinstance(action_id, str) else None,
        value if isinstance(value, str) else None,
    )


def _user_id(payload: dict[object, object]) -> str | None:
    user = payload.get("user")
    if not isinstance(user, dict):
        return None
    user_id = user.get("id")
    if not isinstance(user_id, str) or user_id == "":
        return None
    return user_id


def _message_ts(payload: dict[object, object]) -> str | None:
    message = payload.get("message")
    if not isinstance(message, dict):
        return None
    ts = message.get("ts")
    return ts if isinstance(ts, str) else None


def _channel_id(payload: dict[object, object]) -> str | None:
    channel = payload.get("channel")
    if not isinstance(channel, dict):
        return None
    channel_id = channel.get("id")
    return channel_id if isinstance(channel_id, str) else None
