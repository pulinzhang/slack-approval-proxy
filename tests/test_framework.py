"""Framework boot: schema and control tower shell."""

import sqlite3

from fastapi.testclient import TestClient

from app.config import database_file
from main import create_app


def test_startup_creates_schema_and_serves_the_page() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "Integration Control Tower" in response.text
    with sqlite3.connect(database_file()) as connection:
        names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert {
        "approval_requests",
        "message_exchanges",
        "http_call_logs",
        "business_audit_logs",
    } <= names
