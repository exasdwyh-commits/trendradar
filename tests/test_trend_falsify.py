import sqlite3
from pathlib import Path

from trendradar.db import init_db
from trendradar.trends import apply_trend_signal

ROOT = Path(__file__).resolve().parents[1]


def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn, ROOT / "schema.sql")
    return conn


def candidate(conn, index):
    cluster = f"cl{index}"
    cid = f"c{index}"
    conn.execute(
        "INSERT INTO story_clusters(id,canonical_title,lane) VALUES(?,?,?)",
        (cluster,f"Event {index}","COMPANY"),
    )
    conn.execute(
        """
        INSERT INTO candidates(id,cluster_id,title,profit_pool,action)
        VALUES(?,?,?,?,?)
        """,
        (cid,cluster,f"Event {index}","software margin","TRACK"),
    )
    conn.commit()
    return conn.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone()


def test_one_subject_cannot_promote_trend_to_active():
    conn = db()
    first = candidate(conn, 1)
    trend_id = apply_trend_signal(
        conn,
        first,
        {
            "action":"PROPOSE_NEW",
            "name":"Enterprise AI spending shifts to agents",
            "judgement":"Enterprise AI budgets are moving from chat tools to workflow agents.",
            "stage":"EMERGING",
            "momentum":"STRENGTHENING",
            "stance":"SUPPORT",
            "evidence_summary":"First event",
            "subject_key":"company-a",
        },
        "test-model",
    )

    second = candidate(conn, 2)
    apply_trend_signal(
        conn,
        second,
        {
            "action":"MATCH_EXISTING",
            "trend_id":trend_id,
            "stance":"SUPPORT",
            "evidence_summary":"Second event from the same company",
            "subject_key":"company-a",
        },
        "test-model",
    )
    assert conn.execute("SELECT status FROM trends WHERE id=?", (trend_id,)).fetchone()["status"] == "DRAFT"

    third = candidate(conn, 3)
    apply_trend_signal(
        conn,
        third,
        {
            "action":"MATCH_EXISTING",
            "trend_id":trend_id,
            "stance":"SUPPORT",
            "evidence_summary":"Independent event from another company",
            "subject_key":"company-b",
        },
        "test-model",
    )
    assert conn.execute("SELECT status FROM trends WHERE id=?", (trend_id,)).fetchone()["status"] == "ACTIVE"
