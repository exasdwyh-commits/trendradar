"""Stage 2 of the cost pyramid: classify rule-filtered signals (batched, cheap model or rules)."""

from __future__ import annotations

import json
import sqlite3

from ..providers.classifier import ClassifyInput, get_classifier


def classify_pending(
    conn: sqlite3.Connection,
    *,
    min_rule_score: float,
    limit: int = 2000,
    job_id: str | None = None,
    signal_ids: list[str] | None = None,
) -> dict:
    where = "s.status='new' AND s.dedup_of IS NULL AND s.source_id NOT IN (SELECT id FROM sources WHERE kind='story')"
    params: list = []
    if signal_ids is not None:
        if not signal_ids:
            return {"considered": 0, "filtered": 0, "classified": 0, "pain": 0}
        where = f"s.id IN ({','.join('?' * len(signal_ids))}) AND s.dedup_of IS NULL AND s.status IN ('new','filtered')"
        params = list(signal_ids)
    rows = conn.execute(
        f"SELECT s.* FROM signals s WHERE {where} ORDER BY s.rule_score DESC LIMIT ?", (*params, limit)
    ).fetchall()
    below = [r["id"] for r in rows if r["rule_score"] < min_rule_score]
    conn.executemany("UPDATE signals SET status='filtered' WHERE id=?", [(i,) for i in below])
    todo = [r for r in rows if r["rule_score"] >= min_rule_score]
    inputs = [
        ClassifyInput(
            id=r["id"],
            external_id=r["external_id"],
            title=r["title"],
            content=r["content"],
            rule_score=r["rule_score"],
            rule_matches=json.loads(r["metadata_json"] or "{}").get("rule_matches", []),
            source=r["source_id"],
            origin=r["origin"],
        )
        for r in todo
    ]
    results = get_classifier().classify(inputs, conn=conn, job_id=job_id) if inputs else []
    pain = 0
    for c in results:
        conn.execute(
            """INSERT OR REPLACE INTO signal_classifications(signal_id,classifier,is_pain,relevance,persona,category,confidence,reason,model)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                c.id,
                c.classifier,
                1 if c.is_pain else 0,
                c.relevance,
                c.persona,
                c.category,
                c.confidence,
                c.reason,
                c.model,
            ),
        )
        conn.execute(
            "UPDATE signals SET status=? WHERE id=?", ("classified" if c.is_pain else "filtered", c.id)
        )
        pain += 1 if c.is_pain else 0
    conn.commit()
    return {
        "considered": len(rows),
        "filtered": len(below) + (len(results) - pain),
        "classified": len(results),
        "pain": pain,
    }
