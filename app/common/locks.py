"""In-process locks for one worker. The create lock is per request_id."""

import threading

_guard = threading.Lock()
_held_requests: set[str] = set()
_callback_ids: set[str] = set()
_exchange_ids: set[str] = set()


def try_acquire(request_id: str) -> bool:
    with _guard:
        if request_id in _held_requests:
            return False
        _held_requests.add(request_id)
        return True


def release(request_id: str) -> None:
    with _guard:
        _held_requests.discard(request_id)


def is_held(request_id: str) -> bool:
    with _guard:
        return request_id in _held_requests


def mark_callback(request_id: str) -> bool:
    with _guard:
        if request_id in _callback_ids:
            return False
        _callback_ids.add(request_id)
        return True


def unmark_callback(request_id: str) -> None:
    with _guard:
        _callback_ids.discard(request_id)


def callback_is_running(request_id: str) -> bool:
    with _guard:
        return request_id in _callback_ids


def mark_exchange(exchange_id: str) -> None:
    with _guard:
        _exchange_ids.add(exchange_id)


def unmark_exchange(exchange_id: str) -> None:
    with _guard:
        _exchange_ids.discard(exchange_id)


def exchange_ids_in_flight() -> set[str]:
    with _guard:
        return set(_exchange_ids)
