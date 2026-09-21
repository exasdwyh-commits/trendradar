from __future__ import annotations

import json
import sqlite3
import uuid

from .content import ensure_document_for_article
from .llm import chat_json
from .prompts import CRITIC_SYSTEM, RESEARCH_SYSTEM, THESIS_SYSTEM, WRITER_SYSTEM


def candidate_material(conn: sqlite3.Connection, candidate_id: str) -> dict:
    candidate = conn.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
    if not candidate:
        raise KeyError("candidate not found")
    sources = conn.execute(
        """
        SELECT i.id,i.title,i.url,i.summary,i.content,i.kind,i.source_role,i.source_id,i.published_at,
               i.evidence_score,i.commercial_score
        FROM cluster_items ci
        JOIN intelligence i ON i.id=ci.intelligence_id
        WHERE ci.cluster_id=?
        ORDER BY i.evidence_score DESC,i.published_at DESC
        """,
        (candidate["cluster_id"],),
    ).fetchall()
    return {"candidate": dict(candidate), "evidence": [dict(r) for r in sources]}


def latest_research(conn: sqlite3.Connection, candidate_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM research WHERE candidate_id=? ORDER BY created_at DESC LIMIT 1",
        (candidate_id,),
    ).fetchone()
    if not row:
        return None
    data = dict(row)
    for key in ("facts_json","claims_json","inferences_json"):
        data[key.removesuffix("_json")] = json.loads(data.pop(key) or "[]")
    return data


def research_candidate(conn: sqlite3.Connection, candidate_id: str) -> str:
    material = candidate_material(conn, candidate_id)
    data, model = chat_json("RESEARCH_MODEL", RESEARCH_SYSTEM, json.dumps(material, ensure_ascii=False))
    rid = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO research(id,candidate_id,facts_json,claims_json,inferences_json,strongest_counter,evidence_gap,generated_by)
        VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            rid,candidate_id,
            json.dumps(data.get("facts",[]),ensure_ascii=False),
            json.dumps(data.get("claims",[]),ensure_ascii=False),
            json.dumps(data.get("inferences",[]),ensure_ascii=False),
            data.get("strongest_counter",""),
            data.get("evidence_gap",""),
            model,
        ),
    )
    conn.commit()
    return rid


def propose_thesis(conn: sqlite3.Connection, candidate_id: str) -> str:
    research = latest_research(conn, candidate_id)
    if not research:
        raise ValueError("research is required before thesis")
    material = candidate_material(conn, candidate_id)
    data, model = chat_json(
        "RESEARCH_MODEL",
        THESIS_SYSTEM,
        json.dumps({"research": research, **material}, ensure_ascii=False),
    )
    thesis = (data.get("thesis") or "").strip()
    if not thesis:
        raise ValueError("model returned empty thesis")
    tid = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO theses(
          id,candidate_id,thesis,support_json,counter_json,falsification_signal,status,generated_by
        ) VALUES(?,?,?,?,?,?,'PENDING',?)
        """,
        (
            tid,candidate_id,thesis,
            json.dumps(data.get("support",[]),ensure_ascii=False),
            json.dumps(data.get("counter",[]),ensure_ascii=False),
            data.get("falsification_signal",""),
            model,
        ),
    )
    conn.commit()
    return tid


def confirm_thesis(conn: sqlite3.Connection, thesis_id: str, horizon: str = "12个月") -> str:
    thesis = conn.execute("SELECT * FROM theses WHERE id=?", (thesis_id,)).fetchone()
    if not thesis:
        raise KeyError("thesis not found")
    conn.execute(
        "UPDATE theses SET status='CONFIRMED',confirmed_at=CURRENT_TIMESTAMP WHERE id=?",
        (thesis_id,),
    )
    existing = conn.execute("SELECT id FROM judgement_ledger WHERE thesis_id=?", (thesis_id,)).fetchone()
    if existing:
        ledger_id = existing["id"]
    else:
        ledger_id = uuid.uuid4().hex
        conn.execute(
            """
            INSERT INTO judgement_ledger(id,thesis_id,judgement,horizon,falsification_signal)
            VALUES(?,?,?,?,?)
            """,
            (ledger_id,thesis_id,thesis["thesis"],horizon,thesis["falsification_signal"]),
        )
    conn.commit()
    return ledger_id


def hold_thesis(conn: sqlite3.Connection, thesis_id: str) -> None:
    conn.execute("UPDATE theses SET status='HELD' WHERE id=?", (thesis_id,))
    conn.commit()


def draft_article(conn: sqlite3.Connection, thesis_id: str) -> tuple[str,str]:
    thesis = conn.execute("SELECT * FROM theses WHERE id=?", (thesis_id,)).fetchone()
    if not thesis:
        raise KeyError("thesis not found")
    if thesis["status"] != "CONFIRMED":
        raise ValueError("thesis must be confirmed before drafting")
    material = candidate_material(conn, thesis["candidate_id"])
    research = latest_research(conn, thesis["candidate_id"])
    payload = {"thesis": dict(thesis), "research": research, **material}
    data, model = chat_json("WRITING_MODEL", WRITER_SYSTEM, json.dumps(payload, ensure_ascii=False))
    aid = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO articles(id,candidate_id,thesis_id,title,outline,body,status,generated_by)
        VALUES(?,?,?,?,?,?,'CHALLENGE',?)
        """,
        (
            aid,thesis["candidate_id"],thesis_id,
            data.get("title",""),
            json.dumps(data.get("outline",[]),ensure_ascii=False),
            data.get("body",""),
            model,
        ),
    )
    conn.commit()
    document_id=ensure_document_for_article(conn,aid)
    return aid,document_id


def challenge_article(conn: sqlite3.Connection, article_id: str) -> str:
    article = conn.execute("SELECT * FROM articles WHERE id=?", (article_id,)).fetchone()
    if not article:
        raise KeyError("article not found")
    material = candidate_material(conn, article["candidate_id"])
    research = latest_research(conn, article["candidate_id"])
    payload = {"article": dict(article), "research": research, **material}
    data, model = chat_json("CRITIC_MODEL", CRITIC_SYSTEM, json.dumps(payload, ensure_ascii=False))
    review_id = uuid.uuid4().hex
    verdict = data.get("verdict","REVISE")
    if verdict not in {"PASS","REVISE","BLOCK"}:
        verdict = "REVISE"
    conn.execute(
        """
        INSERT INTO article_reviews(
          id,article_id,factual_issues,reasoning_issues,strongest_counter,headline_risk,verdict,generated_by
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            review_id,article_id,
            json.dumps(data.get("factual_issues",[]),ensure_ascii=False),
            json.dumps(data.get("reasoning_issues",[]),ensure_ascii=False),
            data.get("strongest_counter",""),
            data.get("headline_risk",""),
            verdict,
            model,
        ),
    )
    conn.execute(
        "UPDATE articles SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
        ("READY" if verdict=="PASS" else "CHALLENGE",article_id),
    )
    conn.commit()
    return review_id


def article_detail(conn: sqlite3.Connection, article_id: str) -> dict | None:
    row = conn.execute(
        """
        SELECT a.*,t.thesis,t.status thesis_status,d.id document_id
        FROM articles a
        JOIN theses t ON t.id=a.thesis_id
        LEFT JOIN documents d ON d.article_id=a.id
        WHERE a.id=?
        """,
        (article_id,),
    ).fetchone()
    if not row:
        return None
    data = dict(row)
    try:
        data["outline"] = json.loads(data.get("outline") or "[]")
    except json.JSONDecodeError:
        data["outline"] = []
    review = conn.execute(
        "SELECT * FROM article_reviews WHERE article_id=? ORDER BY created_at DESC LIMIT 1",
        (article_id,),
    ).fetchone()
    data["latest_review"] = dict(review) if review else None
    return data
