from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("PRODUCTHUNT_MODE", "mock")


@pytest.fixture(autouse=True)
def isolate_model_credentials(monkeypatch):
    """Developer credentials in .env must never turn offline tests into paid API calls."""
    for slot in ("FAST_MODEL", "ANALYSIS_MODEL", "WRITING_MODEL", "EMBEDDING_MODEL", "MODEL"):
        for suffix in ("BASE_URL", "API_KEY", "MODEL"):
            monkeypatch.setenv(f"{slot}_{suffix}", "")
    # TestClient sends Host: testserver; real deployments only trust loopback by default.
    monkeypatch.setenv("ALLOWED_HOSTS", "testserver")


@pytest.fixture()
def conn(tmp_path) -> sqlite3.Connection:
    from trendradar.db.connection import connect
    from trendradar.db.migrate import migrate

    c = connect(tmp_path / "test.db")
    migrate(c)
    yield c
    c.close()


@pytest.fixture()
def fixture_llm():
    from trendradar.providers.llm import FixtureLLM, set_llm

    provider = FixtureLLM()
    set_llm(provider)
    yield provider
    set_llm(None)


@pytest.fixture()
def mock_adapters():
    from trendradar.core.config import sources_path
    from trendradar.sources.registry import build_adapters, load_source_configs

    configs = load_source_configs(sources_path(ROOT))
    return configs, [a for a in build_adapters(configs) if a.mode == "mock"]


@pytest.fixture()
def seeded(conn, fixture_llm):
    from trendradar.jobs import seed_demo

    result = seed_demo(conn)
    assert result["status"] == "success", result
    return conn
