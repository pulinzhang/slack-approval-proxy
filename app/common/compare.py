"""Constant-time secret compare."""

import hmac


def secrets_match(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)
