"""Approval, callback, and trace behavior against a mocked Slack API."""

import hashlib
import hmac
import json
import time
from collections.abc import Iterator
from urllib.parse import urlencode

import httpx
import pytest
from fastapi.testclient import TestClient

from app.database import create_tables, transaction
from app.services.approval.callback.runner import wait_for_callbacks
from main import create_app

_KEY = {"X-API-Key": "test-key"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    create_tables()
    with transaction() as connection:
        connection.execute("DELETE FROM http_call_logs")
        connection.execute("DELETE FROM business_audit_logs")
        connection.execute("DELETE FROM message_exchanges")
        connection.execute("DELETE FROM approval_requests")
    with TestClient(create_app()) as test_client:
        yield test_client
    wait_for_callbacks()


@pytest.fixture
def slack_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str | None]]:
    calls: list[tuple[str, str, str | None]] = []

    def fake(method: str, url: str, headers: dict[str, str], body: str | None) -> httpx.Response:
        del headers
        calls.append((method, url, body))
        if "chat.postMessage" in url:
            return httpx.Response(200, json={"ok": True, "ts": "111.222"})
        if "chat.update" in url:
            return httpx.Response(200, json={"ok": True, "ts": "111.222"})
        if "conversations.history" in url:
            return httpx.Response(200, json={"ok": True, "messages": []})
        if url.startswith("https://erp.example/fail"):
            return httpx.Response(503, text="connection reset")
        return httpx.Response(200, json={"success": True})

    monkeypatch.setattr("app.services.slack.service.send", fake)
    monkeypatch.setattr("app.services.approval.callback.delivery.send", fake)
    monkeypatch.setattr("app.services.approval.callback.orchestrator.pause", lambda _seconds: None)
    return calls


def _create(
    client: TestClient,
    request_id: str = "demo-req-001",
    callback: str = "https://erp.example/hooks",
) -> httpx.Response:
    return client.post(
        "/api/v1/approvals",
        headers=_KEY,
        json={
            "request_id": request_id,
            "system_source": "ERP-System",
            "callback_url": callback,
            "title": "Purchase order approval #PO-2026-001",
            "details": {"amount": "$12,500.00", "vendor": "Acme Corp", "token": "secret-value"},
            "timeout_minutes": 30,
        },
    )


def _sign(raw: bytes) -> dict[str, str]:
    timestamp = str(int(time.time()))
    digest = hmac.new(b"", b"v0:" + timestamp.encode() + b":" + raw, hashlib.sha256).hexdigest()
    return {
        "X-Slack-Request-Timestamp": timestamp,
        "X-Slack-Signature": f"v0={digest}",
        "Content-Type": "application/x-www-form-urlencoded",
    }


def _click(client: TestClient, request_id: str, action: str, ts: str = "111.222") -> httpx.Response:
    raw = urlencode(
        {
            "payload": json.dumps(
                {
                    "user": {"id": "U012AB3CD"},
                    "channel": {"id": "C012"},
                    "message": {"ts": ts},
                    "actions": [{"action_id": action, "value": request_id}],
                }
            )
        }
    ).encode()
    return client.post("/api/v1/slack/interactive", content=raw, headers=_sign(raw))


def test_create_is_idempotent_until_decided(
    client: TestClient, slack_calls: list[tuple[str, str, str | None]]
) -> None:
    created = _create(client)
    assert created.status_code == 200
    assert created.json()["result"] == "created"
    assert created.json()["status"] == "pending"
    duplicate = _create(client)
    assert duplicate.status_code == 409
    assert duplicate.json()["request_id"] == "demo-req-001"
    posts = [url for _method, url, _body in slack_calls if "chat.postMessage" in url]
    assert len(posts) == 1


def test_reject_records_callback_and_replay(
    client: TestClient, slack_calls: list[tuple[str, str, str | None]]
) -> None:
    del slack_calls
    _create(client)
    clicked = _click(client, "demo-req-001", "reject_request")
    assert clicked.status_code == 200
    wait_for_callbacks()
    status = client.get("/api/v1/approvals/demo-req-001", headers=_KEY)
    assert status.status_code == 200
    assert status.json()["status"] == "rejected"
    assert status.json()["callback_state"] == "delivered"
    replay = _create(client)
    assert replay.status_code == 200
    assert replay.json()["result"] == "already_decided"
    trace = client.get("/api/v1/approvals/demo-req-001/trace", headers=_KEY)
    assert trace.status_code == 200
    operations = {item["operation"] for item in trace.json()["message_exchanges"]}
    assert {"create_approval", "slack_post_message", "callback"} <= operations
    assert (
        len(
            {
                item["correlation_id"]
                for item in trace.json()["message_exchanges"]
                if item["operation"] != "read_trace"
            }
        )
        >= 1
    )


def test_callback_retries_keep_each_attempt(
    client: TestClient, slack_calls: list[tuple[str, str, str | None]]
) -> None:
    del slack_calls
    _create(client, callback="https://erp.example/fail")
    assert _click(client, "demo-req-001", "approve_request").status_code == 200
    wait_for_callbacks()
    status = client.get("/api/v1/approvals/demo-req-001", headers=_KEY)
    assert status.json()["callback_state"] == "exhausted"
    assert status.json()["callback_error_log"].startswith("HTTP 503:")
    trace = client.get("/api/v1/approvals/demo-req-001/trace", headers=_KEY)
    attempts = [
        item for item in trace.json()["message_exchanges"] if item["operation"] == "callback"
    ]
    assert len(attempts) == 4
    assert attempts[0]["request_body"]
    assert attempts[0]["response_body"]


def test_slack_rejection_and_validation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def rejected(
        method: str, url: str, headers: dict[str, str], body: str | None
    ) -> httpx.Response:
        del method, headers, body
        if "chat.postMessage" in url:
            return httpx.Response(200, json={"ok": False, "error": "channel_not_found"})
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr("app.services.slack.service.send", rejected)
    failed = _create(client, request_id="demo-req-002")
    assert failed.status_code == 502
    assert "channel_not_found" in failed.json()["message"]
    current = client.get("/api/v1/approvals/demo-req-002", headers=_KEY)
    assert current.json()["status"] == "failed"
    invalid = client.post("/api/v1/approvals", headers=_KEY, json={"request_id": "x"})
    assert invalid.status_code == 422
    assert invalid.json()["error"] == "ValidationError"
    assert client.post("/api/v1/approvals", json={"request_id": "x"}).status_code == 401


def test_bad_signature_does_not_write(
    client: TestClient, slack_calls: list[tuple[str, str, str | None]]
) -> None:
    del slack_calls
    raw = b"payload=%7B%7D"
    response = client.post(
        "/api/v1/slack/interactive",
        content=raw,
        headers={"X-Slack-Request-Timestamp": "1", "X-Slack-Signature": "v0=nope"},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "InvalidSignature"


def test_exchange_list_masks_secrets(
    client: TestClient, slack_calls: list[tuple[str, str, str | None]]
) -> None:
    del slack_calls
    _create(client)
    listed = client.get("/api/v1/message-exchanges", headers=_KEY)
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1
    assert all(item["operation"] != "list_exchanges" for item in listed.json()["items"])
    exchange_id = next(
        item["exchange_id"]
        for item in listed.json()["items"]
        if item["operation"] == "create_approval"
    )
    detail = client.get(f"/api/v1/message-exchanges/{exchange_id}", headers=_KEY)
    assert detail.status_code == 200
    assert '"token":"***"' in detail.json()["request_body"]
    summary = client.get("/api/v1/message-exchanges/summary", headers=_KEY)
    assert summary.status_code == 200
    assert summary.json()["approvals_pending"] == 1


class SlackScript:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None]] = []
        self.post = "ok"
        self.messages: list[dict[str, object]] = []
        self.callback_status = 200
        self.callback_body: dict[str, object] = {"success": True}

    def send(
        self, method: str, url: str, headers: dict[str, str], body: str | None
    ) -> httpx.Response:
        del headers
        self.calls.append((method, url, body))
        if "chat.postMessage" in url:
            if self.post == "timeout":
                raise httpx.TimeoutException("timed out")
            if self.post == "rejected":
                return httpx.Response(200, json={"ok": False, "error": "channel_not_found"})
            return httpx.Response(200, json={"ok": True, "ts": "111.222"})
        if "chat.update" in url:
            return httpx.Response(200, json={"ok": True, "ts": "111.222"})
        if "conversations.history" in url:
            return httpx.Response(200, json={"ok": True, "messages": self.messages})
        return httpx.Response(self.callback_status, json=self.callback_body)


@pytest.fixture
def script(monkeypatch: pytest.MonkeyPatch) -> SlackScript:
    slack = SlackScript()
    monkeypatch.setattr("app.services.slack.service.send", slack.send)
    monkeypatch.setattr("app.services.approval.callback.delivery.send", slack.send)
    monkeypatch.setattr("app.services.approval.callback.orchestrator.pause", lambda _seconds: None)
    return slack


def _posts(slack: SlackScript) -> list[str | None]:
    return [body for _method, url, body in slack.calls if "chat.postMessage" in url]


def test_unknown_slack_stays_posting(client: TestClient, script: SlackScript) -> None:
    script.post = "timeout"
    failed = _create(client, "posting-1")
    assert failed.status_code == 502
    assert failed.json()["message"] == "Slack outcome unknown; retry the same request_id"
    current = client.get("/api/v1/approvals/posting-1", headers=_KEY)
    assert current.json()["status"] == "posting"


def test_reconcile_hit_does_not_post_again(client: TestClient, script: SlackScript) -> None:
    script.post = "timeout"
    _create(client, "recon-hit")
    script.post = "ok"
    script.messages = [
        {
            "ts": "333.444",
            "metadata": {"event_payload": {"request_id": "recon-hit"}},
        }
    ]
    recovered = _create(client, "recon-hit")
    assert recovered.status_code == 200
    assert recovered.json()["result"] == "created"
    assert recovered.json()["status"] == "pending"
    assert len(_posts(script)) == 1


def test_reconcile_miss_redrives_on_the_same_post(client: TestClient, script: SlackScript) -> None:
    script.post = "timeout"
    _create(client, "recon-miss")
    script.post = "ok"
    recovered = _create(client, "recon-miss")
    assert recovered.status_code == 200
    assert recovered.json()["status"] == "pending"
    assert len(_posts(script)) == 2


def test_failed_redrive_keeps_correlation_id(client: TestClient, script: SlackScript) -> None:
    script.post = "rejected"
    failed = _create(client, "redrive-1")
    assert failed.status_code == 502
    before = client.get("/api/v1/approvals/redrive-1", headers=_KEY).json()
    assert before["status"] == "failed"
    script.post = "ok"
    again = _create(client, "redrive-1")
    assert again.status_code == 200
    assert again.json()["correlation_id"] == before["correlation_id"]
    assert again.json()["status"] == "pending"
    assert len(_posts(script)) == 2


def test_lock_already_held_is_in_progress(client: TestClient, script: SlackScript) -> None:
    del script
    from app.common.locks import release, try_acquire

    assert try_acquire("locked-1")
    try:
        busy = _create(client, "locked-1")
    finally:
        release("locked-1")
    assert busy.status_code == 409
    assert busy.json()["message"] == "A create for this ID is still in progress"
    assert busy.json()["request_id"] == "locked-1"


def test_stale_card_leaves_the_row(client: TestClient, script: SlackScript) -> None:
    _create(client, "stale-1")
    clicked = _click(client, "stale-1", "approve_request", ts="999.000")
    assert clicked.status_code == 200
    assert clicked.content == b""
    current = client.get("/api/v1/approvals/stale-1", headers=_KEY).json()
    assert current["status"] == "pending"
    assert current["callback_state"] is None
    updates = [body or "" for _method, url, body in script.calls if "chat.update" in url]
    assert updates
    assert "replaced by a newer request" in updates[0]


def test_other_action_does_not_decide(client: TestClient, script: SlackScript) -> None:
    del script
    _create(client, "ignore-1")
    clicked = _click(client, "ignore-1", "view_details")
    assert clicked.status_code == 200
    current = client.get("/api/v1/approvals/ignore-1", headers=_KEY).json()
    assert current["status"] == "pending"
    assert current["decided_by"] is None


def test_scanner_expires_pending_and_delivers(client: TestClient, script: SlackScript) -> None:
    del script
    _create(client, "expire-1")
    with transaction() as connection:
        connection.execute(
            "UPDATE approval_requests SET expires_at = ? WHERE request_id = ?",
            ("2020-01-01T00:00:00Z", "expire-1"),
        )
    from app.services.approval.scan.orchestrator import ScanOrchestrator

    ScanOrchestrator().execute()
    wait_for_callbacks()
    current = client.get("/api/v1/approvals/expire-1", headers=_KEY).json()
    assert current["status"] == "expired"
    assert current["decided_by"] is None
    assert current["callback_state"] == "delivered"


def test_scanner_miss_does_not_post_again(client: TestClient, script: SlackScript) -> None:
    script.post = "timeout"
    _create(client, "scan-miss")
    with transaction() as connection:
        connection.execute(
            "UPDATE approval_requests SET created_at = ? WHERE request_id = ?",
            ("2020-01-01T00:00:00Z", "scan-miss"),
        )
    from app.services.approval.scan.orchestrator import ScanOrchestrator

    ScanOrchestrator().execute()
    current = client.get("/api/v1/approvals/scan-miss", headers=_KEY).json()
    assert current["status"] == "failed"
    assert len(_posts(script)) == 1


def test_callback_body_and_soft_failure(client: TestClient, script: SlackScript) -> None:
    script.callback_body = {"success": False, "status": "rejected"}
    _create(client, "soft-1", callback="https://erp.example/soft")
    assert _click(client, "soft-1", "reject_request").status_code == 200
    wait_for_callbacks()
    current = client.get("/api/v1/approvals/soft-1", headers=_KEY).json()
    assert current["status"] == "rejected"
    assert current["callback_state"] == "exhausted"
    payloads = [
        json.loads(body)
        for _method, url, body in script.calls
        if url.startswith("https://erp.example/soft") and body
    ]
    assert len(payloads) == 4
    assert payloads[0]["request_id"] == "soft-1"
    assert payloads[0]["status"] == "rejected"
    assert payloads[0]["decided_by"] == "U012AB3CD"
    assert payloads[0]["decided_at"]


def test_missing_approval_is_404(client: TestClient, script: SlackScript) -> None:
    del script
    missing = client.get("/api/v1/approvals/missing-req", headers=_KEY)
    assert missing.status_code == 404
    assert missing.json()["message"] == "Approval request not found"
