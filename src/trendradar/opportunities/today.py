"""Today selection: 1–5 high-quality opportunities per day, never padded with mediocre ones."""

from __future__ import annotations

import sqlite3

from ..core.timeutil import day_key


def select_today(
    conn: sqlite3.Connection,
    *,
    min_score: float,
    min_confidence: float,
    max_items: int = 5,
    day: str | None = None,
) -> list[dict]:
    day = day or day_key()
    rows = conn.execute(
        """SELECT o.id, o.opportunity_score, o.confidence, o.pain_cluster_id, pc.persona, pc.category FROM opportunities o
           JOIN pain_clusters pc ON pc.id=o.pain_cluster_id
           WHERE o.status NOT IN ('rejected','archived') AND o.session_id IS NULL AND o.opportunity_score>=? AND o.confidence>=?
           ORDER BY o.opportunity_score DESC, o.confidence DESC""",
        (min_score, min_confidence),
    ).fetchall()
    picked: list[dict] = []
    seen_persona_cat: set[tuple] = set()
    for r in rows:
        key = (r["persona"], r["category"])
        if (
            key in seen_persona_cat and len(rows) > max_items
        ):  # prefer diversity when there is enough to choose from
            continue
        seen_persona_cat.add(key)
        picked.append(dict(r))
        if len(picked) >= max_items:
            break
    conn.execute("DELETE FROM today_picks WHERE day=?", (day,))
    for rank, r in enumerate(picked, 1):
        reason = f"score {r['opportunity_score']:.0f} ≥ {min_score:.0f}, confidence {r['confidence']:.0f} ≥ {min_confidence:.0f}"
        conn.execute(
            "INSERT INTO today_picks(day,opportunity_id,rank,reason) VALUES(?,?,?,?)",
            (day, r["id"], rank, reason),
        )
    conn.commit()
    return picked
