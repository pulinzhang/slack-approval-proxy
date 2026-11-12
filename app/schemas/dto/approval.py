"""Create-approval input."""

from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, field_validator


class CreateApprovalBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    request_id: str
    system_source: str
    callback_url: str
    title: str
    details: dict[str, str] | None = None
    timeout_minutes: int

    @field_validator("request_id")
    @classmethod
    def _request_id(cls, value: str) -> str:
        if value != value.strip() or not 1 <= len(value) <= 128:
            raise ValueError("must be 1 to 128 characters with no leading or trailing space")
        return value

    @field_validator("system_source")
    @classmethod
    def _system_source(cls, value: str) -> str:
        if not 1 <= len(value) <= 128:
            raise ValueError("must be 1 to 128 characters")
        return value

    @field_validator("callback_url")
    @classmethod
    def _callback_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or len(value) > 2048:
            raise ValueError("must be an http or https URL of at most 2048 characters")
        return value

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        if not 1 <= len(value) <= 150:
            raise ValueError("must be 1 to 150 characters")
        return value

    @field_validator("details")
    @classmethod
    def _details(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is not None and len(value) > 10:
            raise ValueError("must be an object of at most 10 string values")
        return value

    @field_validator("timeout_minutes")
    @classmethod
    def _timeout_minutes(cls, value: int) -> int:
        if not 1 <= value <= 10080:
            raise ValueError("must be an integer from 1 to 10080")
        return value
