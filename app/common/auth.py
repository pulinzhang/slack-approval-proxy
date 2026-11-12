"""Shared API-key check and header copy."""

from fastapi import Header

from app.common.compare import secrets_match
from app.config import get_settings
from app.exceptions.base import UnauthorizedError


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    if x_api_key is None or not secrets_match(x_api_key, get_settings().PROXY_API_KEY):
        raise UnauthorizedError()


def header_map(pairs: list[tuple[str, str]]) -> dict[str, str]:
    return dict(pairs)
