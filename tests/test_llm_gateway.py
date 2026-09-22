import json
import sqlite3
from pathlib import Path

import httpx
import pytest

from trendradar import llm
from trendradar.db import init_db

ROOT = Path(__file__).resolve().parents[1]


class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = {}
        self.request = httpx.Request("POST", "https://fake.example/chat/completions")

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=self.request,
                response=self,
            )


class FakeClient:
    def __init__(self, *args, **kwargs):
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return FakeResponse(429)
        return FakeResponse(
            200,
            {
                "choices":[{"message":{"content":json.dumps({"ok": True})}}],
                "usage":{"prompt_tokens":10,"completion_tokens":4},
            },
        )


def test_ai_gateway_retries_transient_failure_and_logs_telemetry(monkeypatch):
    monkeypatch.setenv("FAST_MODEL_BASE_URL", "https://fake.example")
    monkeypatch.setenv("FAST_MODEL_API_KEY", "secret")
    monkeypatch.setenv("FAST_MODEL_MODEL", "fake-model")
    monkeypatch.setenv("FAST_MODEL_INPUT_CNY_PER_M", "100")
    monkeypatch.setenv("FAST_MODEL_OUTPUT_CNY_PER_M", "200")
    monkeypatch.delenv("AI_24H_BUDGET_CNY", raising=False)
    monkeypatch.setattr(llm.httpx, "Client", FakeClient)
    monkeypatch.setattr(llm.time, "sleep", lambda _: None)

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn, ROOT / "schema.sql")

    data, model = llm.chat_json(
        "FAST_MODEL",
        "system",
        "user",
        conn=conn,
        task="gateway_test",
        max_attempts=3,
    )

    assert data == {"ok": True}
    assert model == "fake-model"
    row = conn.execute("SELECT * FROM ai_runs ORDER BY id DESC LIMIT 1").fetchone()
    assert row["ok"] == 1
    assert row["attempts"] == 2
    assert row["retries"] == 1
    assert row["input_tokens"] == 10
    assert row["output_tokens"] == 4
    assert abs(row["cost"] - 0.0018) < 1e-9



def test_ai_gateway_blocks_when_rolling_budget_is_reached(monkeypatch):
    monkeypatch.setenv("FAST_MODEL_BASE_URL", "https://fake.example")
    monkeypatch.setenv("FAST_MODEL_API_KEY", "secret")
    monkeypatch.setenv("FAST_MODEL_MODEL", "fake-model")
    monkeypatch.setenv("AI_24H_BUDGET_CNY", "0.5")

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn, ROOT / "schema.sql")
    conn.execute(
        """
        INSERT INTO ai_runs(task,slot,model,cost,duration_ms,ok)
        VALUES('previous','FAST_MODEL','fake-model',0.6,1,1)
        """
    )
    conn.commit()

    with pytest.raises(RuntimeError, match="budget reached"):
        llm.chat_json(
            "FAST_MODEL","system","user",conn=conn,task="blocked"
        )

    row = conn.execute(
        "SELECT * FROM ai_runs WHERE task='blocked' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    assert row["ok"] == 0
    assert "budget reached" in row["error"]
