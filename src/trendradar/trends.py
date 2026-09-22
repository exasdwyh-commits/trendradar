from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from .llm import chat_json, slot_enabled
from .prompts import WORLD_MODEL_SYSTEM

STAGES = {"EMERGING","ACCELERATING","MAINSTREAM"}
MOMENTA = {"STRENGTHENING","STABLE","DIVERGING","WEAKENING","REVERSING"}
STANCES = {"SUPPORT","COUNTER","UNCERTAIN"}


def _trend_id(name: str) -> str:
    return hashlib.sha256(f"trend|{name.strip().lower()}".encode()).hexdigest()[:24]


def _safe(value: str | None, allowed: set[str], fallback: str) -> str:
    value = (value or "").upper()
    return value if value in allowed else fallback


def apply_trend_signal(conn: sqlite3.Connection, candidate: sqlite3.Row, signal: dict, model: str) -> str | None:
    action = signal.get("action")
    if action == "MATCH_EXISTING":
        trend_id = signal.get("trend_id")
        current = conn.execute("SELECT * FROM trends WHERE id=?", (trend_id,)).fetchone()
        if not current:
            return None
        new_judgement = signal.get("judgement") or current["judgement"]
        new_stage = _safe(signal.get("stage"), STAGES, current["stage"])
        new_momentum = _safe(signal.get("momentum"), MOMENTA, current["momentum"])
        changed = (
            new_judgement != current["judgement"]
            or new_stage != current["stage"]
            or new_momentum != current["momentum"]
        )
        if changed:
            conn.execute(
                """
                INSERT INTO trend_revisions(
                  id,trend_id,old_judgement,new_judgement,old_stage,new_stage,
                  old_momentum,new_momentum,reason
                ) VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    uuid.uuid4().hex,trend_id,current["judgement"],new_judgement,
                    current["stage"],new_stage,current["momentum"],new_momentum,
                    signal.get("evidence_summary") or f"updated by {model}",
                ),
            )
        conn.execute(
            """
            UPDATE trends SET judgement=?,stage=?,momentum=?,
              china_relevance=COALESCE(NULLIF(?,''),china_relevance),
              watch_next=COALESCE(NULLIF(?,''),watch_next),
              updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (
                new_judgement,new_stage,new_momentum,
                signal.get("china_relevance",""),signal.get("watch_next",""),trend_id,
            ),
        )
    elif action == "PROPOSE_NEW":
        name = (signal.get("name") or "").strip()
        judgement = (signal.get("judgement") or "").strip()
        if not name or not judgement:
            return None
        trend_id = _trend_id(name)
        conn.execute(
            """
            INSERT OR IGNORE INTO trends(
              id,name,judgement,stage,momentum,china_relevance,profit_pool,watch_next,status
            ) VALUES(?,?,?,?,?,?,?,?,'DRAFT')
            """,
            (
                trend_id,name,judgement,
                _safe(signal.get("stage"),STAGES,"EMERGING"),
                _safe(signal.get("momentum"),MOMENTA,"STABLE"),
                signal.get("china_relevance",""),
                candidate["profit_pool"] if "profit_pool" in candidate.keys() else "",
                signal.get("watch_next",""),
            ),
        )
    else:
        return None

    stance = _safe(signal.get("stance"), STANCES, "UNCERTAIN")
    event_key = candidate["cluster_id"]
    summary = signal.get("evidence_summary") or candidate["title"]
    conn.execute(
        """
        INSERT OR IGNORE INTO trend_evidence(
          id,trend_id,cluster_id,stance,event_key,summary,subject_key
        ) VALUES(?,?,?,?,?,?,?)
        """,
        (
            uuid.uuid4().hex,trend_id,candidate["cluster_id"],stance,event_key,summary,
            signal.get("subject_key") or None,
        ),
    )

    counts = conn.execute(
        """
        SELECT
          COUNT(DISTINCT CASE WHEN stance='SUPPORT' THEN event_key END) AS support_events,
          COUNT(DISTINCT CASE WHEN stance='SUPPORT' THEN subject_key END) AS support_subjects
        FROM trend_evidence WHERE trend_id=?
        """,
        (trend_id,),
    ).fetchone()
    if counts["support_events"] >= 2 and counts["support_subjects"] >= 2:
        conn.execute("UPDATE trends SET status='ACTIVE' WHERE id=?", (trend_id,))
    return trend_id


def world_model_update(conn: sqlite3.Connection, days: int = 7) -> dict:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    trends = conn.execute(
        """
        SELECT t.*,
          SUM(CASE WHEN te.stance='SUPPORT' THEN 1 ELSE 0 END) support_count,
          SUM(CASE WHEN te.stance='COUNTER' THEN 1 ELSE 0 END) counter_count,
          SUM(CASE WHEN te.stance='UNCERTAIN' THEN 1 ELSE 0 END) uncertain_count
        FROM trends t
        LEFT JOIN trend_evidence te ON te.trend_id=t.id
        GROUP BY t.id
        ORDER BY t.updated_at DESC
        """
    ).fetchall()
    revisions = conn.execute(
        "SELECT * FROM trend_revisions WHERE created_at >= ? ORDER BY created_at DESC",
        (start.isoformat(),),
    ).fetchall()

    if not slot_enabled("COGNITION_MODEL"):
        return {
            "enabled": False,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "items": [dict(t) for t in trends],
        }

    payload = {"trends": [dict(t) for t in trends], "recent_revisions": [dict(r) for r in revisions]}
    data, model = chat_json(
        "COGNITION_MODEL",
        WORLD_MODEL_SYSTEM,
        json.dumps(payload, ensure_ascii=False),
        timeout=90,
        conn=conn,
        task="world_model",
    )
    uid = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO world_model_updates(
          id,period_start,period_end,strengthened_json,weakened_json,
          diverging_json,new_json,summary,generated_by
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (
            uid,start.isoformat(),end.isoformat(),
            json.dumps(data.get("strengthened",[]),ensure_ascii=False),
            json.dumps(data.get("weakened",[]),ensure_ascii=False),
            json.dumps(data.get("diverging",[]),ensure_ascii=False),
            json.dumps(data.get("new",[]),ensure_ascii=False),
            data.get("summary",""),model,
        ),
    )
    conn.commit()
    return {"enabled": True, "id": uid, **data, "model": model}


def latest_world_model_update(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT * FROM world_model_updates ORDER BY created_at DESC LIMIT 1").fetchone()
    if not row:
        return None
    result = dict(row)
    for key in ("strengthened_json","weakened_json","diverging_json","new_json"):
        result[key.removesuffix("_json")] = json.loads(result.pop(key) or "[]")
    return result
