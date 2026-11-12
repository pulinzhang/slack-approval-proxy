"""Mask secrets before a message is stored."""

import json

from app.config import get_settings

_HEADER_NAMES = {"authorization", "x-api-key", "cookie", "x-slack-signature"}
_BODY_KEYS = {
    "national_id",
    "id_card",
    "bank_account",
    "bank_card",
    "password",
    "access_token",
    "refresh_token",
    "api_key",
    "token",
    "secret",
}
_BODY_LIMIT = 1024 * 1024


def mask_headers(headers: dict[str, str]) -> str:
    token = get_settings().SLACK_BOT_TOKEN
    masked: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in _HEADER_NAMES or (token != "" and token in value):
            masked[key] = "***"
        else:
            masked[key] = value
    return json.dumps(masked, ensure_ascii=False, separators=(",", ":"))


def mask_body(body: str | None) -> tuple[str | None, int]:
    if body is None:
        return None, 0
    masked = _mask_json(body)
    raw = masked.encode("utf-8")
    if len(raw) > _BODY_LIMIT:
        return raw[:_BODY_LIMIT].decode("utf-8", errors="ignore"), 1
    return masked, 0


def headers_object(stored: str | None) -> dict[str, str] | None:
    if stored is None:
        return None
    parsed = _json_object(stored)
    if parsed is None:
        return {}
    result: dict[str, str] = {}
    for key, value in parsed.items():
        if isinstance(key, str) and isinstance(value, str):
            result[key] = value
    return result


def _mask_json(body: str) -> str:
    parsed = _json_object(body)
    if parsed is None:
        return body
    masked: dict[str, object] = {}
    for key, value in parsed.items():
        if not isinstance(key, str):
            continue
        if key in _BODY_KEYS:
            masked[key] = "***"
        elif isinstance(value, dict):
            masked[key] = _mask_nested(value)
        else:
            masked[key] = value
    return json.dumps(masked, ensure_ascii=False, separators=(",", ":"))


def _mask_nested(value: dict[object, object]) -> dict[str, object]:
    nested: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            continue
        nested[key] = "***" if key in _BODY_KEYS else item
    return nested


def _json_object(body: str) -> dict[object, object] | None:
    try:
        parsed: object = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed
