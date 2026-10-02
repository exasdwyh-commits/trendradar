"""Trend detection on daily snapshots: velocity, acceleration, emergence. Absolute counts alone are
never used — a cluster with 2/day for weeks and 15/day for the last three days is what we look for."""

from __future__ import annotations

import sqlite3
from datetime import timedelta

from ..core.timeutil import day_key, utcnow


def snapshot_pain_clusters(conn: sqlite3.Connection, *, days_back: int = 30) -> int:
    """(Re)build per-day counts of new signals for every pain cluster over the last `days_back` days."""
    since = (utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    rows = conn.execute(
        """
        SELECT pci.cluster_id, substr(COALESCE(s.created_at, s.fetched_at),1,10) day, COUNT(*) n, COUNT(DISTINCT s.source_id) sources
        FROM pain_cluster_items pci JOIN signals s ON s.id=pci.signal_id JOIN pain_clusters pc ON pc.id=pci.cluster_id
        WHERE pc.session_id IS NULL AND substr(COALESCE(s.created_at, s.fetched_at),1,10) >= ?
        GROUP BY pci.cluster_id, day
        """,
        (since,),
    ).fetchall()
    cum: dict[str, int] = {}
    written = 0
    for r in sorted(rows, key=lambda x: (x["cluster_id"], x["day"])):
        cum[r["cluster_id"]] = cum.get(r["cluster_id"], 0) + int(r["n"])
        conn.execute(
            "INSERT OR REPLACE INTO trend_snapshots(subject_type,subject_id,day,new_items,cum_items,unique_sources) VALUES('pain_cluster',?,?,?,?,?)",
            (r["cluster_id"], r["day"], int(r["n"]), cum[r["cluster_id"]], int(r["sources"])),
        )
        written += 1
    conn.commit()
    return written


def series(conn: sqlite3.Connection, subject_type: str, subject_id: str, days: int = 35) -> list[int]:
    """Daily new-item counts for the last `days` days ending today (zero-filled, oldest first)."""
    today = utcnow().date()
    rows = conn.execute(
        "SELECT day, new_items FROM trend_snapshots WHERE subject_type=? AND subject_id=?",
        (subject_type, subject_id),
    ).fetchall()
    by_day = {r["day"]: int(r["new_items"]) for r in rows}
    return [by_day.get((today - timedelta(days=i)).isoformat(), 0) for i in range(days - 1, -1, -1)]


RECENT_DAYS = 7
BASELINE_DAYS = 21
BASELINE_FLOOR = 0.4  # signals/day — below this a baseline is treated as "no history" (≈3 signals/week)


def velocity_metrics(counts: list[int]) -> dict:
    """velocity = mean/day(last 7d) ÷ max(mean/day(prior 21d), 0.4); acceleration = velocity − velocity one week earlier.

    Relative rates, not absolute counts: a cluster at 2/day for weeks then 15/day this week is what we want to catch.
    """
    need = RECENT_DAYS * 2 + BASELINE_DAYS
    if len(counts) < need:
        counts = [0] * (need - len(counts)) + counts

    def vel(seq: list[int]) -> float:
        recent = seq[-RECENT_DAYS:]
        prior = seq[-(RECENT_DAYS + BASELINE_DAYS) : -RECENT_DAYS]
        recent_mean = sum(recent) / RECENT_DAYS
        prior_mean = sum(prior) / max(len(prior), 1)
        return round(recent_mean / max(prior_mean, BASELINE_FLOOR), 2)

    v_now = vel(counts)
    v_prev = vel(counts[:-RECENT_DAYS])
    return {
        "velocity": v_now,
        "acceleration": round(v_now - v_prev, 2),
        "total": sum(counts),
        "recent_7d": sum(counts[-RECENT_DAYS:]),
    }


def stage_for(velocity: float, signal_count: int, source_count: int, recent_7d: int) -> str:
    if signal_count >= 5 and source_count >= 2 and velocity >= 3.0:
        return "emerging"
    if velocity >= 1.5 and recent_7d >= 2:
        return "growing"
    if signal_count < 3:
        return "new"
    if velocity < 0.5:
        return "fading"
    return "stable"


def update_cluster_trends(conn: sqlite3.Connection) -> dict:
    snapshot_pain_clusters(conn)
    rows = conn.execute(
        "SELECT id, signal_count, source_count FROM pain_clusters WHERE session_id IS NULL"
    ).fetchall()
    stages: dict[str, int] = {}
    for r in rows:
        m = velocity_metrics(series(conn, "pain_cluster", r["id"]))
        stage = stage_for(m["velocity"], int(r["signal_count"]), int(r["source_count"]), m["recent_7d"])
        conn.execute(
            "UPDATE pain_clusters SET velocity=?, acceleration=?, stage=? WHERE id=?",
            (m["velocity"], m["acceleration"], stage, r["id"]),
        )
        stages[stage] = stages.get(stage, 0) + 1
    conn.commit()
    return {"clusters": len(rows), "stages": stages, "today": day_key()}
