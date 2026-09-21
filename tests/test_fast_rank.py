import sqlite3
from pathlib import Path

from trendradar.db import init_db
from trendradar.fast_rank import refine_candidates

ROOT=Path(__file__).resolve().parents[1]


def test_fast_rank_is_explicitly_disabled_without_model(monkeypatch):
    for key in ("FAST_MODEL_BASE_URL","FAST_MODEL_API_KEY","FAST_MODEL_MODEL"):
        monkeypatch.delenv(key,raising=False)
    conn=sqlite3.connect(":memory:")
    conn.row_factory=sqlite3.Row
    init_db(conn,ROOT/"schema.sql")
    result=refine_candidates(conn)
    assert result["enabled"] is False
    assert result["processed"] == 0
