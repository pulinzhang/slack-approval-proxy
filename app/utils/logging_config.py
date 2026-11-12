"""Console and rotating file logs. ERROR lines stay on stderr."""

import logging
import sys
from logging.handlers import RotatingFileHandler

from app.config import get_settings


class LoggerConfig:
    """Configure the root logger once at process start."""

    _configured = False

    @classmethod
    def configure(cls) -> None:
        if cls._configured:
            return
        settings = get_settings()
        settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
        root_logger = logging.getLogger()
        root_logger.handlers.clear()
        level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
        root_logger.setLevel(level)
        root_logger.addHandler(_console_handler())
        root_logger.addHandler(_file_handler(settings.LOG_DIR / "app.log"))
        cls._configured = True
        logging.info("logging ready level=%s", settings.LOG_LEVEL)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def _console_handler() -> logging.Handler:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", "%H:%M:%S")
    )
    return handler


def _file_handler(path: object) -> logging.Handler:
    handler = RotatingFileHandler(
        filename=str(path),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", "%Y-%m-%d %H:%M:%S")
    )
    return handler
