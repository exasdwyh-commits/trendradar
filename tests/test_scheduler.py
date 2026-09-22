import sqlite3
from pathlib import Path

from trendradar.db import init_db
from trendradar.scheduler import should_run_daily

ROOT = Path(__file__).resolve().parents[1]


def test_scheduler_returns_boolean():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn, ROOT / "schema.sql")
    assert isinstance(should_run_daily(conn, "Asia/Shanghai", 0), bool)
