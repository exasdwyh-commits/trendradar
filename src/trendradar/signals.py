from __future__ import annotations

import json
import sqlite3
from collections import defaultdict


SIGNAL_NEW = "NEW"
SIGNAL_RISING = "RISING"
SIGNAL_TRACKING = "TRACKING"


def _source_count(snapshot_json: str | None) -> int:
    if not snapshot_json:
        return 0
    try:
        snapshot = json.loads(snapshot_json)
    except (TypeError, json.JSONDecodeError):
        return 0
    evidence = snapshot.get("evidence") or []
    return len({str(item.get("source_id")) for item in evidence if item.get("source_id")})


def _signal_from_history(rows: list[sqlite3.Row]) -> dict:
    current = rows[0]
    current_sources = _source_count(current["snapshot_json"])
    if len(rows) == 1:
        return {
            "status": SIGNAL_NEW,
            "history_count": 1,
            "first_seen_at": current["run_at"],
            "last_seen_at": current["run_at"],
            "content_rank": current["content_rank"],
            "cognition_rank": current["cognition_rank"],
            "content_score": float(current["content_score"] or 0),
            "score_delta": 0.0,
            "rank_delta": 0,
            "source_count": current_sources,
            "source_delta": 0,
        }

    previous = rows[1]
    previous_sources = _source_count(previous["snapshot_json"])
    score_delta = round(
        float(current["content_score"] or 0) - float(previous["content_score"] or 0),
        2,
    )
    current_rank = current["content_rank"]
    previous_rank = previous["content_rank"]
    rank_delta = (
        int(previous_rank) - int(current_rank)
        if current_rank is not None and previous_rank is not None
        else 0
    )
    source_delta = current_sources - previous_sources
    rising = score_delta >= 5 or rank_delta >= 3 or source_delta >= 1
    return {
        "status": SIGNAL_RISING if rising else SIGNAL_TRACKING,
        "history_count": len(rows),
        "first_seen_at": rows[-1]["run_at"],
        "last_seen_at": current["run_at"],
        "content_rank": current_rank,
        "cognition_rank": current["cognition_rank"],
        "content_score": float(current["content_score"] or 0),
        "score_delta": score_delta,
        "rank_delta": rank_delta,
        "source_count": current_sources,
        "source_delta": source_delta,
    }


def candidate_signal_states(
    conn: sqlite3.Connection,
    candidate_ids: list[str] | None = None,
    *,
    days: int = 90,
) -> dict[str, dict]:
    params: list[object] = [f"-{max(1, min(int(days), 365))} days"]
    where = "WHERE datetime(cr.created_at) >= datetime('now', ?)"
    if candidate_ids:
        placeholders = ",".join("?" for _ in candidate_ids)
        where += f" AND cri.candidate_id IN ({placeholders})"
        params.extend(candidate_ids)

    rows = conn.execute(
        f"""
        SELECT cri.candidate_id,cri.content_rank,cri.cognition_rank,
               cri.content_score,cri.cognition_score,cri.action,cri.snapshot_json,
               cr.created_at run_at
        FROM candidate_run_items cri
        JOIN candidate_runs cr ON cr.id=cri.run_id
        {where}
        ORDER BY cri.candidate_id,datetime(cr.created_at) DESC
        """,
        params,
    ).fetchall()
    grouped: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        grouped[row["candidate_id"]].append(row)
    return {candidate_id: _signal_from_history(history) for candidate_id, history in grouped.items()}


def enrich_candidates(conn: sqlite3.Connection, items: list[dict]) -> list[dict]:
    ids = [str(item.get("id")) for item in items if item.get("id")]
    states = candidate_signal_states(conn, ids) if ids else {}
    enriched = []
    for item in items:
        payload = dict(item)
        state = states.get(str(payload.get("id")))
        if state:
            payload["signal"] = state
        enriched.append(payload)
    return enriched


def signal_board(conn: sqlite3.Connection, limit: int = 12) -> dict:
    run = conn.execute(
        "SELECT id,created_at,settings_json FROM candidate_runs ORDER BY datetime(created_at) DESC LIMIT 1"
    ).fetchone()
    if not run:
        return {
            "run_id": None,
            "run_at": None,
            "ranking_mode": None,
            "summary": {SIGNAL_NEW: 0, SIGNAL_RISING: 0, SIGNAL_TRACKING: 0},
            "items": [],
        }

    rows = conn.execute(
        """
        SELECT cri.candidate_id,cri.snapshot_json
        FROM candidate_run_items cri
        WHERE cri.run_id=?
        ORDER BY COALESCE(cri.content_rank,9999),COALESCE(cri.cognition_rank,9999)
        LIMIT ?
        """,
        (run["id"], max(1, min(int(limit), 50))),
    ).fetchall()
    ids = [row["candidate_id"] for row in rows]
    states = candidate_signal_states(conn, ids)
    items = []
    for row in rows:
        try:
            snapshot = json.loads(row["snapshot_json"] or "{}")
        except json.JSONDecodeError:
            snapshot = {}
        candidate = dict(snapshot.get("candidate") or {})
        candidate.setdefault("id", row["candidate_id"])
        candidate["signal"] = states.get(row["candidate_id"], {
            "status": SIGNAL_TRACKING,
            "history_count": 0,
        })
        items.append(candidate)

    summary = {SIGNAL_NEW: 0, SIGNAL_RISING: 0, SIGNAL_TRACKING: 0}
    for item in items:
        status = (item.get("signal") or {}).get("status", SIGNAL_TRACKING)
        summary[status] = summary.get(status, 0) + 1

    try:
        settings = json.loads(run["settings_json"] or "{}")
    except json.JSONDecodeError:
        settings = {}
    return {
        "run_id": run["id"],
        "run_at": run["created_at"],
        "ranking_mode": settings.get("ranking_mode", "RULE"),
        "summary": summary,
        "items": items,
    }
