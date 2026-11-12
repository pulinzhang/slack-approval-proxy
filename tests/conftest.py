"""Point tests at a local SQLite file before the app reads settings."""

import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_DB = _ROOT / "data" / "test_approvals.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB.as_posix()}"
os.environ["PROXY_API_KEY"] = "test-key"
os.environ["IS_DEBUG"] = "false"
os.environ["SLACK_BOT_TOKEN"] = "xoxb-test"
os.environ["SLACK_SIGNING_SECRET"] = ""
os.environ["SLACK_CHANNEL_ID"] = "C012"
