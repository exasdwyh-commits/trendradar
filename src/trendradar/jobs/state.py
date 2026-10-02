"""Durable job state: heartbeats, cross-process "is a job running?" and crash recovery.

Jobs were already recorded in ``jobs`` / ``job_steps``, but "currently running" lived only in an
in-memory dict of the API process. A crash, restart or a job started from the CLI / daemon left
rows stuck in ``running`` forever and let two pipelines write the same SQLite file at once.

Now every ``JobRun`` refreshes ``jobs.heartbeat_at`` from a small thread. A ``running`` row whose
heartbeat is older than ``STALE_AFTER`` belongs to a dead process: it (and its running steps) is
marked ``failed`` with an ``interrupted:`` error on startup and whenever the running job is queried.
"""

from __future__ import annotations

import os
import socket
import sqlite3
import threading
from datetime import datetime, timedelta

from ..core.logging import get_logger
from ..core.timeutil import iso, utcnow

log = get_logger("jobs.state")

HEARTBEAT_SECONDS = 15.0
STALE_AFTER = timedelta(seconds=90)
INTERRUPTED_PREFIX = "interrupted:"


def current_owner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def database_file(conn: sqlite3.Connection) -> str | None:
    """Path of the main database file; None for in-memory databases."""
    row = conn.execute("PRAGMA database_list").fetchone()
    return (row[2] or None) if row else None


def is_interrupted(error: str | None) -> bool:
    return bool(error) and str(error).startswith(INTERRUPTED_PREFIX)


class Heartbeat:
    """Refresh ``jobs.heartbeat_at`` from a daemon thread with its own connection."""

    def __init__(self, conn: sqlite3.Connection, job_id: str, *, interval: float = HEARTBEAT_SECONDS) -> None:
        self.job_id = job_id
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        path = database_file(conn)
        if path:
            self._thread = threading.Thread(
                target=self._run, args=(path,), name=f"job-heartbeat-{job_id[:8]}", daemon=True
            )
            self._thread.start()

    def _run(self, path: str) -> None:
        from ..db.connection import connect

        conn = connect(path)
        try:
            while not self._stop.wait(self.interval):
                cur = conn.execute(
                    "UPDATE jobs SET heartbeat_at=? WHERE id=? AND status='running'",
                    (iso(utcnow()), self.job_id),
                )
                conn.commit()
                if cur.rowcount == 0:  # finished, recovered or deleted elsewhere
                    return
        except sqlite3.Error:
            log.warning("heartbeat for job %s stopped", self.job_id, exc_info=True)
        finally:
            conn.close()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)


def recover_interrupted(conn: sqlite3.Connection, *, now: datetime | None = None) -> int:
    """Mark ``running`` jobs whose heartbeat went stale as failed/interrupted. Returns how many."""
    now = now or utcnow()
    cutoff = iso(now - STALE_AFTER)
    stale = conn.execute(
        "SELECT id, job_type, owner FROM jobs WHERE status='running' AND COALESCE(heartbeat_at, started_at) < ?",
        (cutoff,),
    ).fetchall()
    if not stale:
        return 0
    finished = iso(now)
    for row in stale:
        owner = row["owner"] or "未知进程"
        conn.execute(
            "UPDATE jobs SET status='failed', finished_at=?, error=? WHERE id=? AND status='running'",
            (
                finished,
                f"{INTERRUPTED_PREFIX} 运行该任务的进程（{owner}）已退出或重启，任务未完成",
                row["id"],
            ),
        )
        conn.execute(
            "UPDATE job_steps SET status='failed', finished_at=?, error=? WHERE job_id=? AND status='running'",
            (finished, f"{INTERRUPTED_PREFIX} 进程中断", row["id"]),
        )
        log.warning("job %s (%s) marked interrupted", row["id"], row["job_type"])
    conn.commit()
    return len(stale)


def active_job(conn: sqlite3.Connection) -> dict | None:
    """The live running job in any process sharing this database, after clearing stale rows."""
    recover_interrupted(conn)
    row = conn.execute(
        "SELECT id, job_type, started_at, heartbeat_at, owner FROM jobs WHERE status='running' "
        "ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "type": row["job_type"],
        "started_at": row["started_at"],
        "heartbeat_at": row["heartbeat_at"],
        "owner": row["owner"],
    }
