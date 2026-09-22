from __future__ import annotations

import json
import sqlite3

from .llm import chat_json, slot_enabled
from .prompts import BUSINESS_COGNITION_SYSTEM
from .trends import apply_trend_signal


def _candidate_payload(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> dict:
    existing = conn.execute(
        """
        SELECT id,name,judgement,stage,momentum,status,china_relevance,watch_next
        FROM trends ORDER BY updated_at DESC LIMIT 40
        """
    ).fetchall()
    items = []
    for row in rows:
        evidence = conn.execute(
            """
            SELECT i.id,i.title,i.url,i.summary,i.kind,i.source_role,i.source_id,i.published_at
            FROM cluster_items ci
            JOIN intelligence i ON i.id=ci.intelligence_id
            WHERE ci.cluster_id=?
            ORDER BY i.evidence_score DESC
            """,
            (row["cluster_id"],),
        ).fetchall()
        items.append({"candidate": dict(row), "evidence": [dict(x) for x in evidence]})
    return {"existing_trends": [dict(x) for x in existing], "candidates": items}


def analyze_pending(conn: sqlite3.Connection, limit: int = 12) -> dict:
    if not slot_enabled("COGNITION_MODEL"):
        return {"enabled": False, "processed": 0, "reason": "COGNITION_MODEL not configured"}

    rows = conn.execute(
        """
        SELECT * FROM candidates
        WHERE action != 'SKIP' AND cognition_status IN ('PENDING','FAILED')
        ORDER BY cognition_score DESC, content_score DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    if not rows:
        return {"enabled": True, "processed": 0}

    payload = _candidate_payload(conn, rows)
    try:
        data, model = chat_json(
            "COGNITION_MODEL",
            BUSINESS_COGNITION_SYSTEM,
            json.dumps(payload, ensure_ascii=False),
            timeout=120,
            conn=conn,
            task="cognition",
        )
    except Exception as exc:
        return {
            "enabled": True,
            "processed": 0,
            "error": str(exc)[:500],
            "degraded": True,
        }
    by_id = {r["id"]: r for r in rows}
    processed = 0
    errors: list[str] = []

    for item in data.get("items", []):
        cid = item.get("candidate_id")
        if cid not in by_id:
            continue
        try:
            action = item.get("action", "TRACK")
            if action not in {"WRITE","TRACK","HOLD","SKIP"}:
                action = "HOLD"
            conn.execute(
                """
                UPDATE candidates SET
                  event_summary=?,what_changed=?,why_now=?,profit_pool=?,
                  who_benefits=?,who_loses=?,china_mapping=?,strongest_counter=?,
                  evidence_gap=?,action=?,cognition_status='DONE',generated_by=?,
                  updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    item.get("event_summary",""),item.get("what_changed",""),
                    item.get("why_now",""),item.get("profit_pool",""),
                    item.get("who_benefits",""),item.get("who_loses",""),
                    item.get("china_mapping",""),item.get("strongest_counter",""),
                    item.get("evidence_gap",""),action,model,cid,
                ),
            )
            trend = item.get("trend") or {}
            if trend.get("action") and trend.get("action") != "NONE":
                apply_trend_signal(conn, by_id[cid], trend, model)
            processed += 1
        except Exception as exc:
            conn.execute(
                "UPDATE candidates SET cognition_status='FAILED' WHERE id=?",
                (cid,),
            )
            errors.append(f"{cid}: {str(exc)[:160]}")
    conn.commit()
    return {"enabled": True, "processed": processed, "errors": errors, "model": model}
