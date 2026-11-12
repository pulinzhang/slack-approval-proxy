"""Slack request signature. A failure does not write the database."""

import hashlib
import hmac
from datetime import UTC, datetime

from app.common.compare import secrets_match
from app.config import get_settings
from app.exceptions.base import InvalidSignatureError


def verify_signature(raw_body: bytes, timestamp: str | None, signature: str | None) -> None:
    settings = get_settings()
    if timestamp is None or signature is None or not _fresh(timestamp):
        raise InvalidSignatureError()
    base = b"v0:" + timestamp.encode("utf-8") + b":" + raw_body
    digest = hmac.new(
        settings.SLACK_SIGNING_SECRET.encode("utf-8"),
        base,
        hashlib.sha256,
    ).hexdigest()
    if not secrets_match(signature, f"v0={digest}"):
        raise InvalidSignatureError()


def _fresh(timestamp: str) -> bool:
    try:
        sent = int(timestamp)
    except ValueError:
        return False
    now = int(datetime.now(UTC).timestamp())
    return abs(now - sent) <= get_settings().SIGNATURE_MAX_SKEW_SECONDS
