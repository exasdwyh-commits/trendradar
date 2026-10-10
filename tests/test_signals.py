import json
import sqlite3
from pathlib import Path

from trendradar.db import init_db
from trendradar.signals import candidate_signal_states, signal_board


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
        VALUES('c1','cl','Signal candidate',70,72,'TRACK')
        """
    )
    conn.commit()
    return conn


def snapshot(*sources: str) -> str:
    return json.dumps(
        {
            "candidate": {
                "id": "c1",
                "title": "Signal candidate",
                "content_score": 70,
                "cognition_score": 72,
                "action": "TRACK",
                "cognition_status": "DONE",
            },
            "evidence": [{"source_id": source} for source in sources],
        }
    )


def add_run(conn, run_id: str, when_sql: str, rank: int, score: float, *sources: str):
    conn.execute(
        f"""
        INSERT INTO candidate_runs(id,status,system_top3_json,settings_json,created_at)
        VALUES(?,'FROZEN','[\"c1\"]','{{\"ranking_mode\":\"COGNITION\"}}',datetime('now',{when_sql}))
        """,
        (run_id,),
    )
    conn.execute(
        """
        INSERT INTO candidate_run_items(
          run_id,candidate_id,content_rank,cognition_rank,content_score,cognition_score,action,snapshot_json
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        (run_id,"c1",rank,rank,score,72,"TRACK",snapshot(*sources)),
    )
    conn.commit()


def test_first_appearance_is_new():
    conn = memory_db()
    add_run(conn,"r1","'-1 hour'",4,70,"s1")
    state = candidate_signal_states(conn,["c1"])["c1"]
    assert state["status"] == "NEW"
    assert state["history_count"] == 1
    assert state["source_count"] == 1


def test_score_rank_or_source_growth_marks_rising():
    conn = memory_db()
    add_run(conn,"r1","'-1 day'",7,61,"s1")
    add_run(conn,"r2","'-1 hour'",3,70,"s1","s2")
    state = candidate_signal_states(conn,["c1"])["c1"]
    assert state["status"] == "RISING"
    assert state["rank_delta"] == 4
    assert state["score_delta"] == 9
    assert state["source_delta"] == 1


def test_flat_signal_stays_tracking_and_board_reports_latest_run():
    conn = memory_db()
    add_run(conn,"r1","'-1 day'",3,68,"s1","s2")
    add_run(conn,"r2","'-1 hour'",3,69,"s1","s2")
    state = candidate_signal_states(conn,["c1"])["c1"]
    assert state["status"] == "TRACKING"
    board = signal_board(conn)
    assert board["run_id"] == "r2"
    assert board["ranking_mode"] == "COGNITION"
    assert board["summary"]["TRACKING"] == 1
    assert board["items"][0]["signal"]["history_count"] == 2
