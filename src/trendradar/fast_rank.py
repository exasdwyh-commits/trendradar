from __future__ import annotations

import json
import sqlite3

from .llm import chat_json, slot_enabled
from .prompts import FAST_RANK_SYSTEM


def refine_candidates(conn: sqlite3.Connection, limit: int = 40) -> dict:
    if not slot_enabled("FAST_MODEL"):
        return {"enabled": False, "processed": 0, "reason": "FAST_MODEL not configured"}

    rows = conn.execute(
        """
        SELECT * FROM candidates
        WHERE cognition_status IN ('PENDING','FAILED')
        ORDER BY content_score DESC,cognition_score DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    if not rows:
        return {"enabled": True, "processed": 0}

    payload = []
    for row in rows:
        evidence = conn.execute(
            """
            SELECT i.title,i.summary,i.source_role,i.source_id,i.published_at
            FROM cluster_items ci
            JOIN intelligence i ON i.id=ci.intelligence_id
            WHERE ci.cluster_id=?
            ORDER BY i.evidence_score DESC
            LIMIT 4
            """,
            (row["cluster_id"],),
        ).fetchall()
        evidence_rows = [dict(x) for x in evidence]
        payload.append({
            "candidate_id": row["id"],
            "title": row["title"],
            "rule_content_score": row["content_score"],
            "rule_cognition_score": row["cognition_score"],
            "source_count": len({x["source_id"] for x in evidence_rows}),
            "source_roles": sorted({x["source_role"] for x in evidence_rows}),
            "evidence": evidence_rows,
        })

    try:
        data,model = chat_json(
            "FAST_MODEL",
            FAST_RANK_SYSTEM,
            json.dumps({"candidates":payload},ensure_ascii=False),
            timeout=90,
            conn=conn,
            task="fast_rank",
        )
    except Exception as exc:
        return {
            "enabled": True,
            "processed": 0,
            "error": str(exc)[:500],
            "degraded": True,
        }
    allowed={r["id"]:r for r in rows}
    processed=0
    for item in data.get("items",[]):
        cid=item.get("candidate_id")
        if cid not in allowed:
            continue
        try:
            relevance=max(0.0,min(100.0,float(item.get("business_relevance",50))))
            cognition=max(0.0,min(100.0,float(item.get("cognition_value",50))))
            content=max(0.0,min(100.0,float(item.get("content_value",50))))
        except (TypeError,ValueError):
            continue
        old=allowed[cid]
        evidence_rows = conn.execute(
            """
            SELECT DISTINCT i.source_id,i.source_role
            FROM cluster_items ci
            JOIN intelligence i ON i.id=ci.intelligence_id
            WHERE ci.cluster_id=?
            """,
            (old["cluster_id"],),
        ).fetchall()
        source_count = len({x["source_id"] for x in evidence_rows})
        non_discovery = any(x["source_role"] in {"PRIMARY","VERIFIER"} for x in evidence_rows)
        corroborated = source_count >= 2 and non_discovery
        new_cognition=round(old["cognition_score"]*.35+cognition*.65,2)
        new_content=round(old["content_score"]*.35+content*.65,2)
        keep=bool(item.get("keep",True)) and relevance>=45
        if not keep:
            action="SKIP"
            status="SKIPPED"
        elif new_content>=72 and corroborated:
            action="WRITE"
            status="PENDING"
        elif new_content>=72:
            action="TRACK"
            status="PENDING"
        elif new_content>=52 or new_cognition>=60:
            action="TRACK"
            status="PENDING"
        else:
            action="HOLD"
            status="PENDING"
        conn.execute(
            """
            UPDATE candidates SET cognition_score=?,content_score=?,action=?,
              cognition_status=?,generated_by=?,updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (new_cognition,new_content,action,status,model,cid),
        )
        processed+=1
    conn.commit()
    return {"enabled":True,"processed":processed,"model":model}
