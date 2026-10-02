"""Durable job state (jobs/state.py): heartbeats, crash recovery, cross-process running check."""

from __future__ import annotations

import time
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from trendradar.core.timeutil import iso, utcnow
from trendradar.jobs import state
from trendradar.jobs.pipeline import JobRun


def _insert_job(
    conn, job_id: str, *, age: timedelta, heartbeat: bool = True, job_type: str = "daily"
) -> None:
    stamp = iso(utcnow() - age)
    conn.execute(
        "INSERT INTO jobs(id,job_type,started_at,status,heartbeat_at,owner) VALUES(?,?,?,'running',?,?)",
        (job_id, job_type, stamp, stamp if heartbeat else None, "other-host:1234"),
    )
    conn.execute(
        "INSERT INTO job_steps(job_id,step,started_at,status) VALUES(?,?,?,'running')",
        (job_id, "collect", stamp),
    )
    conn.commit()


def test_jobrun_records_owner_heartbeat_and_releases_on_finish(conn):
    job = JobRun(conn, "collect")
    row = conn.execute("SELECT owner, heartbeat_at FROM jobs WHERE id=?", (job.id,)).fetchone()
    assert row["owner"] == state.current_owner() and row["heartbeat_at"]
    assert state.active_job(conn)["id"] == job.id
    job.finish()
    assert state.active_job(conn) is None
    assert job.heartbeat._thread is None or not job.heartbeat._thread.is_alive()


def test_stale_running_job_is_marked_interrupted_fresh_one_is_kept(conn):
    _insert_job(conn, "stale", age=timedelta(minutes=10))
    _insert_job(conn, "legacy", age=timedelta(days=2), heartbeat=False)  # rows from before migration 0006
    _insert_job(conn, "fresh", age=timedelta(seconds=5))
    assert state.recover_interrupted(conn) == 2
    rows = {r["id"]: r for r in conn.execute("SELECT id, status, error, finished_at FROM jobs")}
    assert rows["stale"]["status"] == "failed" and state.is_interrupted(rows["stale"]["error"])
    assert rows["stale"]["finished_at"] and rows["legacy"]["status"] == "failed"
    assert rows["fresh"]["status"] == "running"
    steps = {r["job_id"]: r["status"] for r in conn.execute("SELECT job_id, status FROM job_steps")}
    assert steps == {"stale": "failed", "legacy": "failed", "fresh": "running"}
    assert state.active_job(conn)["id"] == "fresh"


def test_heartbeat_thread_refreshes_and_stops_when_job_ends(conn):
    _insert_job(conn, "hb", age=timedelta(minutes=10))
    before = conn.execute("SELECT heartbeat_at FROM jobs WHERE id='hb'").fetchone()[0]
    beat = state.Heartbeat(conn, "hb", interval=0.05)
    time.sleep(0.4)
    after = conn.execute("SELECT heartbeat_at FROM jobs WHERE id='hb'").fetchone()[0]
    assert after > before
    conn.execute("UPDATE jobs SET status='success' WHERE id='hb'")
    conn.commit()
    time.sleep(0.3)
    assert beat._thread is not None and not beat._thread.is_alive()
    beat.stop()


def test_collect_only_failure_does_not_leave_job_running(conn, monkeypatch):
    from trendradar.jobs import pipeline

    def boom(*_, **__):
        raise RuntimeError("adapters exploded")

    monkeypatch.setattr(pipeline, "enabled_adapters", boom)
    result = pipeline.run_collect_only(conn)
    assert result["status"] == "failed" and state.active_job(conn) is None


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    from trendradar.core.settings import reset_settings
    from trendradar.db.connection import connect
    from trendradar.db.migrate import migrate

    reset_settings()
    conn = connect(tmp_path / "data" / "trendradar.db")
    migrate(conn)
    yield conn
    conn.close()
    reset_settings()


def test_startup_recovers_and_api_reports_interrupted(api, tmp_path):
    from trendradar.api import create_app

    _insert_job(api, "crashed", age=timedelta(hours=1))
    with TestClient(create_app(static_dir=tmp_path / "nope")) as c:
        body = c.get("/api/jobs").json()
        item = next(i for i in body["items"] if i["id"] == "crashed")
        assert item["status"] == "failed" and item["interrupted"] is True
        assert body["running"]["type"] is None


def test_job_running_in_another_process_blocks_new_runs(api, tmp_path):
    from trendradar.api import create_app

    _insert_job(api, "daemon-job", age=timedelta(seconds=3), job_type="brief")
    with TestClient(create_app(static_dir=tmp_path / "nope")) as c:
        assert c.get("/api/health").json()["running_job"]["type"] == "brief"
        r = c.post("/api/jobs/run", json={"type": "collect", "mock_only": True})
        assert r.status_code == 409 and "brief" in r.json()["detail"]["message"]
