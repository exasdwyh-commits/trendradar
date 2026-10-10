from pathlib import Path

import pytest

from trendradar.db import connect, init_db, schema_version
from trendradar.learning import (
    feedback_summary,
    record_candidate_feedback,
    source_health_history,
)


ROOT = Path(__file__).resolve().parents[1]


def _db(tmp_path):
    conn = connect(tmp_path / "trendradar.sqlite")
    init_db(conn, ROOT / "schema.sql")
    return conn


def _seed_source(conn):
    conn.execute(
        """
        INSERT INTO sources(id,name,lane,role,type,url,enabled)
        VALUES('src-1','Source One','ai','PRIMARY','rss','https://example.com/feed',1)
        """
    )
    conn.commit()


def _seed_candidate(conn):
    conn.execute(
        "INSERT INTO story_clusters(id,canonical_title,lane) VALUES('cluster-1','A useful signal','ai')"
    )
    conn.execute(
        """
        INSERT INTO candidates(id,cluster_id,title,action)
        VALUES('candidate-1','cluster-1','A useful signal','TRACK')
        """
    )
    conn.commit()


def test_schema_v6_installs_learning_tables_and_source_history_trigger(tmp_path):
    conn = _db(tmp_path)
    _seed_source(conn)

    assert schema_version(conn) == 6
    conn.execute(
        """
        INSERT INTO source_health(
          source_id,last_attempt_at,last_success_at,last_error,
          consecutive_failures,last_item_count,latency_ms
        ) VALUES('src-1','2026-10-10T01:00:00+00:00','2026-10-10T01:00:00+00:00',NULL,0,12,345)
        """
    )
    conn.execute(
        """
        UPDATE source_health
        SET last_attempt_at='2026-10-10T02:00:00+00:00',last_error='timeout',
            consecutive_failures=1,last_item_count=0,latency_ms=18000
        WHERE source_id='src-1'
        """
    )
    conn.commit()

    rows = conn.execute(
        "SELECT status,item_count,latency_ms,error FROM source_health_history ORDER BY id"
    ).fetchall()
    assert [row["status"] for row in rows] == ["SUCCESS", "FAILED"]
    assert rows[0]["item_count"] == 12
    assert rows[1]["error"] == "timeout"


def test_candidate_feedback_is_append_only_and_summarized(tmp_path):
    conn = _db(tmp_path)
    _seed_candidate(conn)

    saved = record_candidate_feedback(conn, "candidate-1", "saved", "worth tracking")
    published = record_candidate_feedback(conn, "candidate-1", "PUBLISHED")

    assert saved["weight"] == 3
    assert published["weight"] == 8
    summary = feedback_summary(conn)
    assert summary["candidates"][0]["weighted_signal"] == 11
    assert summary["candidates"][0]["feedback_count"] == 2


def test_candidate_feedback_rejects_unknown_action_or_candidate(tmp_path):
    conn = _db(tmp_path)
    _seed_candidate(conn)

    with pytest.raises(ValueError):
        record_candidate_feedback(conn, "candidate-1", "LIKE")
    with pytest.raises(LookupError):
        record_candidate_feedback(conn, "missing", "SAVED")


def test_source_health_history_endpoint_helper_aggregates(tmp_path):
    conn = _db(tmp_path)
    _seed_source(conn)
    conn.execute(
        """
        INSERT INTO source_health(
          source_id,last_attempt_at,last_success_at,last_error,
          consecutive_failures,last_item_count,latency_ms
        ) VALUES('src-1',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,NULL,0,5,120)
        """
    )
    conn.commit()

    payload = source_health_history(conn, days=7, limit=20)
    assert payload["aggregate"][0]["source_id"] == "src-1"
    assert payload["aggregate"][0]["successes"] == 1
    assert payload["items"][0]["status"] == "SUCCESS"
