"""Startup and shutdown. This process creates the tables and starts the minute scan."""

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import ensure_directories
from app.database import create_tables
from app.services.approval.scan.job import run_scan
from app.utils.logging_config import get_logger

logger = get_logger("bootstrap.lifecycle")
_scheduler: BackgroundScheduler | None = None


def on_startup() -> None:
    ensure_directories()
    create_tables()
    _start_scheduler()
    logger.info("application started")


def on_shutdown() -> None:
    _stop_scheduler()
    logger.info("application stopped")


def _start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_scan, "interval", seconds=60, id="approval_scan", replace_existing=True)
    scheduler.start()
    _scheduler = scheduler


def _stop_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None
