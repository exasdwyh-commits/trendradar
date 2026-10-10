import json
import sqlite3
from pathlib import Path

from trendradar.board import render_signal_board
from trendradar.db import init_db


ROOT = Path(__file__).resolve().parents[1]


def memory_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn, ROOT / "schema.sql")
    conn.execute("INSERT INTO story_clusters(id,canonical_title,lane) VALUES('cl','Signal','COMPANY')")
    conn.execute(
        """
        INSERT INTO candidates(id,cluster_id,title,content_score,cognition_score,action)
        VALUES('c1','cl','<script>alert(1)</script> opportunity',80,82,'WRITE')
        """
    )
    snapshot = json.dumps(
        {
            "candidate": {
                "id": "c1",
                "title": "<script>alert(1)</script> opportunity",
                "event_summary": "A verified commercial signal",
                "profit_pool": "Enterprise software revenue",
                "content_score": 80,
                "cognition_score": 82,
                "action": "WRITE",
                "cognition_status": "DONE",
            },
            "evidence": [{"source_id": "official"}, {"source_id": "verifier"}],
        }
    )
    conn.execute(
        """
        INSERT INTO candidate_runs(id,status,system_top3_json,settings_json,created_at)
        VALUES('r1','FROZEN','["c1"]','{"ranking_mode":"COGNITION"}',datetime('now','-1 hour'))
        """
    )
    conn.execute(
        """
        INSERT INTO candidate_run_items(
          run_id,candidate_id,content_rank,cognition_rank,content_score,cognition_score,action,snapshot_json
        ) VALUES('r1','c1',1,1,80,82,'WRITE',?)
        """,
        (snapshot,),
    )
    conn.commit()
    return conn


def test_board_is_self_contained_and_escapes_content():
    page = render_signal_board(memory_db())
    assert "<!doctype html>" in page.lower()
    assert "每日商业信号看板" in page
    assert "COGNITION" in page
    assert "首次出现" in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "<script>alert(1)</script>" not in page
    assert "http-equiv=\"refresh\"" in page


def test_board_has_empty_state_before_first_daily_run():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn, ROOT / "schema.sql")
    page = render_signal_board(conn)
    assert "运行一次 daily" in page
    assert "首次出现" in page
