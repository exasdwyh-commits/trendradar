import json
import sqlite3
from pathlib import Path

from trendradar.db import init_db
from trendradar.evaluation import (
    blind_round_detail,
    calibration_summary,
    ensure_blind_round,
    freeze_candidate_run,
    submit_blind_round,
)

ROOT = Path(__file__).resolve().parents[1]


def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn, ROOT / "schema.sql")
    conn.execute(
        """
        INSERT INTO sources(
          id,name,lane,role,type,url,tier,reliability,business_value,noise,accuracy
        ) VALUES('s','Source','COMPANY','VERIFIER','rss','https://example.com',2,85,80,15,85)
        """
    )
    return conn


def seed_candidates(conn, count=10):
    for i in range(count):
        intel_id = f"i{i}"
        cluster_id = f"cl{i}"
        candidate_id = f"c{i}"
        title = f"Company {i} signs enterprise contract and expands revenue"
        conn.execute(
            """
            INSERT INTO intelligence(
              id,source_id,title,url,canonical_url,summary,content,kind,source_role,lane,
              freshness_score,evidence_score,commercial_score,title_hash
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                intel_id,"s",title,f"https://example.com/{i}",f"https://example.com/{i}",
                "A concrete enterprise contract with commercial impact.","body","CLAIM",
                "VERIFIER","COMPANY",95,85,80,f"h{i}",
            ),
        )
        conn.execute(
            "INSERT INTO story_clusters(id,canonical_title,lane) VALUES(?,?,?)",
            (cluster_id,title,"COMPANY"),
        )
        conn.execute(
            "INSERT INTO cluster_items(cluster_id,intelligence_id) VALUES(?,?)",
            (cluster_id,intel_id),
        )
        conn.execute(
            """
            INSERT INTO candidates(
              id,cluster_id,title,event_summary,cognition_score,content_score,action,cognition_status
            ) VALUES(?,?,?,?,?,?,?,'DONE')
            """,
            (
                candidate_id,cluster_id,title,"A business event",
                70 + i,100 - i,"TRACK",
            ),
        )
    conn.commit()


def test_blind_round_hides_system_ranking_until_submit():
    conn = db()
    seed_candidates(conn, 10)
    run_id = freeze_candidate_run(conn, None, lookback_hours=72, max_items=20)
    round_id = ensure_blind_round(conn, run_id)
    assert round_id

    before = blind_round_detail(conn, round_id)
    assert before["submitted"] is False
    assert "system_top3" not in before
    assert len(before["items"]) == 10

    run = conn.execute("SELECT system_top3_json FROM candidate_runs WHERE id=?", (run_id,)).fetchone()
    system_top3 = json.loads(run["system_top3_json"])
    after = submit_blind_round(conn, round_id, system_top3)

    assert after["submitted"] is True
    assert after["hits"] == 3
    assert after["system_top3"] == system_top3



def test_calibration_summary_tracks_human_and_system_disagreements():
    conn = db()
    seed_candidates(conn, 10)
    run_id = freeze_candidate_run(conn, None, lookback_hours=72, max_items=20)
    round_id = ensure_blind_round(conn, run_id)

    run = conn.execute(
        "SELECT system_top3_json FROM candidate_runs WHERE id=?",
        (run_id,),
    ).fetchone()
    system_top3 = json.loads(run["system_top3_json"])
    blind_ids = [
        row["candidate_id"] for row in conn.execute(
            "SELECT candidate_id FROM blind_items WHERE round_id=? ORDER BY position",
            (round_id,),
        ).fetchall()
    ]
    replacement = next(cid for cid in blind_ids if cid not in system_top3)
    human = [system_top3[0], system_top3[1], replacement]
    submit_blind_round(conn, round_id, human)

    report = calibration_summary(conn)
    assert report["rounds"] == 1
    assert report["diagnostic_only"] is True
    types = {item["type"] for item in report["disagreements"]}
    assert types == {"HUMAN_ONLY","SYSTEM_ONLY"}
