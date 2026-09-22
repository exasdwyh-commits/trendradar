from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def _recent_candidate_rows(
    conn: sqlite3.Connection,
    *,
    lookback_hours: int = 72,
) -> list[sqlite3.Row]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).isoformat()
    return conn.execute(
        """
        SELECT DISTINCT c.*
        FROM candidates c
        JOIN cluster_items ci ON ci.cluster_id=c.cluster_id
        JOIN intelligence i ON i.id=ci.intelligence_id
        WHERE c.action != 'SKIP'
          AND datetime(COALESCE(i.published_at,i.collected_at)) >= datetime(?)
        """,
        (cutoff,),
    ).fetchall()


def _snapshot_candidate(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    evidence = conn.execute(
        """
        SELECT i.id,i.title,i.url,i.summary,i.kind,i.source_role,i.source_id,i.published_at,
               i.evidence_score,i.commercial_score
        FROM cluster_items ci
        JOIN intelligence i ON i.id=ci.intelligence_id
        WHERE ci.cluster_id=?
        ORDER BY i.evidence_score DESC
        LIMIT 8
        """,
        (row["cluster_id"],),
    ).fetchall()
    return {
        "candidate": dict(row),
        "evidence": [dict(x) for x in evidence],
    }


def freeze_candidate_run(
    conn: sqlite3.Connection,
    pipeline_run_id: str | None,
    *,
    lookback_hours: int = 72,
    max_items: int = 20,
) -> str:
    rows = _recent_candidate_rows(conn, lookback_hours=lookback_hours)
    if not rows:
        run_id = uuid.uuid4().hex
        conn.execute(
            """
            INSERT INTO candidate_runs(id,pipeline_run_id,status,system_top3_json,settings_json)
            VALUES(?,?,'FROZEN','[]',?)
            """,
            (run_id,pipeline_run_id,json.dumps({"lookback_hours":lookback_hours},ensure_ascii=False)),
        )
        conn.commit()
        return run_id

    content_sorted = sorted(
        rows,
        key=lambda r: (
            {"WRITE":0,"TRACK":1,"HOLD":2}.get(r["action"],3),
            -float(r["content_score"]),
            -float(r["cognition_score"]),
        ),
    )
    cognition_sorted = sorted(
        rows,
        key=lambda r: (-float(r["cognition_score"]),-float(r["content_score"])),
    )
    content_rank = {r["id"]: i+1 for i,r in enumerate(content_sorted)}
    cognition_rank = {r["id"]: i+1 for i,r in enumerate(cognition_sorted)}

    selected_ids = {
        r["id"] for r in content_sorted[:max_items]
    } | {
        r["id"] for r in cognition_sorted[:max_items]
    }
    selected = [r for r in rows if r["id"] in selected_ids]

    run_id = uuid.uuid4().hex
    top3 = [r["id"] for r in content_sorted[:3]]
    conn.execute(
        """
        INSERT INTO candidate_runs(id,pipeline_run_id,status,system_top3_json,settings_json)
        VALUES(?,?,'FROZEN',?,?)
        """,
        (
            run_id,pipeline_run_id,json.dumps(top3,ensure_ascii=False),
            json.dumps(
                {
                    "lookback_hours":lookback_hours,
                    "max_items":max_items,
                    "content_pool":min(max_items,len(content_sorted)),
                    "cognition_pool":min(max_items,len(cognition_sorted)),
                },
                ensure_ascii=False,
            ),
        ),
    )
    for row in selected:
        conn.execute(
            """
            INSERT INTO candidate_run_items(
              run_id,candidate_id,content_rank,cognition_rank,content_score,cognition_score,
              action,snapshot_json
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                run_id,row["id"],content_rank.get(row["id"]),cognition_rank.get(row["id"]),
                row["content_score"],row["cognition_score"],row["action"],
                json.dumps(_snapshot_candidate(conn,row),ensure_ascii=False),
            ),
        )
    conn.commit()
    return run_id


def ensure_blind_round(
    conn: sqlite3.Connection,
    candidate_run_id: str,
    *,
    timezone_name: str = "Asia/Shanghai",
    sample_size: int = 10,
) -> str | None:
    round_date = datetime.now(ZoneInfo(timezone_name)).date().isoformat()
    existing = conn.execute(
        "SELECT id FROM blind_rounds WHERE round_date=?",
        (round_date,),
    ).fetchone()
    if existing:
        return existing["id"]

    run = conn.execute(
        "SELECT * FROM candidate_runs WHERE id=?",
        (candidate_run_id,),
    ).fetchone()
    if not run:
        raise KeyError("candidate run not found")

    rows = conn.execute(
        """
        SELECT * FROM candidate_run_items
        WHERE run_id=?
        ORDER BY content_rank ASC
        LIMIT ?
        """,
        (candidate_run_id,max(3,sample_size)),
    ).fetchall()
    if len(rows) < 3:
        return None

    system_top3 = json.loads(run["system_top3_json"] or "[]")
    # Deterministic shuffle hides system order while keeping the round reproducible.
    shuffled = sorted(
        rows,
        key=lambda r: hashlib.sha256(
            f"{candidate_run_id}|{r['candidate_id']}".encode()
        ).hexdigest(),
    )
    round_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO blind_rounds(id,candidate_run_id,round_date,system_top3_json)
        VALUES(?,?,?,?)
        """,
        (round_id,candidate_run_id,round_date,json.dumps(system_top3,ensure_ascii=False)),
    )
    conn.executemany(
        "INSERT INTO blind_items(round_id,candidate_id,position) VALUES(?,?,?)",
        [(round_id,r["candidate_id"],i+1) for i,r in enumerate(shuffled)],
    )
    conn.commit()
    return round_id


def _blind_item_payload(conn: sqlite3.Connection, round_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT bi.candidate_id,bi.position,cri.snapshot_json
        FROM blind_items bi
        JOIN blind_rounds br ON br.id=bi.round_id
        JOIN candidate_run_items cri
          ON cri.run_id=br.candidate_run_id AND cri.candidate_id=bi.candidate_id
        WHERE bi.round_id=?
        ORDER BY bi.position
        """,
        (round_id,),
    ).fetchall()
    items = []
    for row in rows:
        snapshot = json.loads(row["snapshot_json"])
        candidate = snapshot.get("candidate") or {}
        evidence = snapshot.get("evidence") or []
        strongest_fact = evidence[0].get("summary") if evidence else ""
        items.append(
            {
                "candidate_id":row["candidate_id"],
                "position":row["position"],
                "title":candidate.get("title",""),
                "event_summary":candidate.get("event_summary") or strongest_fact or "",
            }
        )
    return items


def blind_round_detail(conn: sqlite3.Connection, round_id: str) -> dict:
    row = conn.execute("SELECT * FROM blind_rounds WHERE id=?", (round_id,)).fetchone()
    if not row:
        raise KeyError("blind round not found")
    submitted = bool(row["submitted_at"])
    result = {
        "id":row["id"],
        "round_date":row["round_date"],
        "submitted":submitted,
        "items":_blind_item_payload(conn,round_id),
    }
    if submitted:
        result.update(
            {
                "human_picks":json.loads(row["human_picks_json"] or "[]"),
                "system_top3":json.loads(row["system_top3_json"] or "[]"),
                "hits":row["hits"],
            }
        )
    return result


def latest_blind_round(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT id FROM blind_rounds ORDER BY round_date DESC,created_at DESC LIMIT 1"
    ).fetchone()
    return blind_round_detail(conn,row["id"]) if row else None


def submit_blind_round(
    conn: sqlite3.Connection,
    round_id: str,
    picks: list[str],
) -> dict:
    row = conn.execute("SELECT * FROM blind_rounds WHERE id=?", (round_id,)).fetchone()
    if not row:
        raise KeyError("blind round not found")
    if row["submitted_at"]:
        return blind_round_detail(conn,round_id)
    if len(picks) != 3 or len(set(picks)) != 3:
        raise ValueError("blind evaluation requires exactly 3 unique picks")

    allowed = {
        r["candidate_id"] for r in conn.execute(
            "SELECT candidate_id FROM blind_items WHERE round_id=?",
            (round_id,),
        ).fetchall()
    }
    if not set(picks) <= allowed:
        raise ValueError("picks contain candidates outside this blind round")

    system_top3 = set(json.loads(row["system_top3_json"] or "[]"))
    hits = len(system_top3 & set(picks))
    conn.execute(
        """
        UPDATE blind_rounds
        SET human_picks_json=?,hits=?,submitted_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (json.dumps(picks,ensure_ascii=False),hits,round_id),
    )
    conn.commit()
    return blind_round_detail(conn,round_id)


def evaluation_summary(conn: sqlite3.Connection, recent: int = 14) -> dict:
    rows = conn.execute(
        """
        SELECT id,round_date,hits,submitted_at
        FROM blind_rounds
        WHERE submitted_at IS NOT NULL
        ORDER BY round_date DESC
        LIMIT ?
        """,
        (recent,),
    ).fetchall()
    rounds = [dict(r) for r in rows]
    hits = sum(int(r["hits"] or 0) for r in rows)
    possible = len(rows) * 3
    return {
        "rounds":len(rows),
        "hits":hits,
        "possible":possible,
        "hit_rate":round(hits/possible,4) if possible else None,
        "recent":rounds,
    }
