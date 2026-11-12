"""In-process callback waves shared by decisions and the scanner."""

import threading
import time

from app.common.locks import mark_callback, unmark_callback

_threads: list[threading.Thread] = []


def schedule_callback(request_id: str) -> None:
    if not mark_callback(request_id):
        return
    thread = threading.Thread(
        target=_wave, args=(request_id,), name=f"callback-{request_id}", daemon=True
    )
    _threads.append(thread)
    thread.start()


def wait_for_callbacks() -> None:
    for thread in list(_threads):
        thread.join(timeout=15)
    _threads.clear()


def pause(seconds: float) -> None:
    time.sleep(seconds)


def _wave(request_id: str) -> None:
    from app.services.approval.callback.orchestrator import CallbackOrchestrator

    try:
        CallbackOrchestrator().execute(request_id)
    finally:
        unmark_callback(request_id)
