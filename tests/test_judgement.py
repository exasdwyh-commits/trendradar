import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from trendradar.db import init_db
from trendradar.judgement import horizon_to_review_at, list_judgements, review_judgement

ROOT=Path(__file__).resolve().parents[1]


def db():
    conn=sqlite3.connect(":memory:")
    conn.row_factory=sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn,ROOT/"schema.sql")
    return conn


def test_horizon_uses_calendar_months():
    now=datetime(2026,1,31,12,0,tzinfo=timezone.utc)
    target=horizon_to_review_at("1个月",now=now)
    assert target.startswith("2026-02-28T12:00:00")


def test_review_judgement_updates_result_and_status():
    conn=db()
    conn.execute(
        """
        INSERT INTO judgement_ledger(
          id,judgement,horizon,falsification_signal,review_at
        ) VALUES('j','AI spending thesis','1个月','renewal fails','2026-01-01T00:00:00+00:00')
        """
    )
    conn.commit()

    review_judgement(conn,"j","directionally_right")
    item=list_judgements(conn)[0]

    assert item["result"]=="DIRECTIONALLY_RIGHT"
    assert item["reviewed_at"] is not None
    assert item["review_status"]=="REVIEWED"
