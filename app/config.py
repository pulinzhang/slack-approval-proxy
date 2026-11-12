"""Application settings. Environment variables override the defaults."""

import os
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR: Path = Path(__file__).resolve().parent.parent
ENV: str = os.getenv("APP_ENV", "development")
_IS_DEBUG_ALIAS = AliasChoices("IS_DEBUG", "DEBUG")


class Settings(BaseSettings):
    """Runtime settings loaded from the process environment and `.env`."""

    APP_NAME: str = "Slack Approval Proxy"
    APP_VERSION: str = "0.1.0"
    APP_DESCRIPTION: str = "Cross-system approval cards and message trace"
    IS_DEBUG: bool = Field(default=True, validation_alias=_IS_DEBUG_ALIAS)
    ENV: str = "development"

    HOST: str = "0.0.0.0"
    PORT: int = 8000

    DATABASE_URL: str = f"sqlite:///{BASE_DIR / 'data' / 'approvals.db'}"
    LOG_DIR: Path = BASE_DIR / "logs"
    LOG_LEVEL: str = "INFO"

    SLACK_BOT_TOKEN: str = ""
    SLACK_SIGNING_SECRET: str = ""
    SLACK_CHANNEL_ID: str = ""
    PROXY_API_KEY: str = ""
    SIGNATURE_MAX_SKEW_SECONDS: int = 300

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def ensure_directories() -> None:
    settings = get_settings()
    settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
    database_parent = _database_path(settings.DATABASE_URL).parent
    database_parent.mkdir(parents=True, exist_ok=True)


def database_file() -> Path:
    return _database_path(get_settings().DATABASE_URL)


def _database_path(database_url: str) -> Path:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError("DATABASE_URL must start with sqlite:///")
    raw = database_url.removeprefix(prefix)
    path = Path(raw)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path
