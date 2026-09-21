from __future__ import annotations

import json
import sqlite3
import uuid

from .llm import chat_json
from .prompts import CRITIC_SYSTEM, RESEARCH_SYSTEM, WRITER_SYSTEM


def _candidate_material(conn: sqlite3.Connection, candidate_id: str) -> dict:
    candidate = conn.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
    if not candidate:
        raise KeyError("candidate not found")
    sources = conn.execute(
        """
        SELECT i.title,i.url,i.summary,i.kind,i.source_role,i.source_id,i.published_at
        FROM cluster_items ci
        JOIN intelligence i ON i.id=ci.intelligence_id
        WHERE ci.cluster_id=?
        """,
        (candidate["cluster_id"],),
    ).fetchall()
    return {"candidate": dict(candidate), "evidence": [dict(r) for r in sources]}


def research_candidate(conn: sqlite3.Connection, candidate_id: str) -> str:
    material = _candidate_material(conn, candidate_id)
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


def create_thesis(conn: sqlite3.Connection, candidate_id: str, thesis: str, generated_by: str = "human") -> str:
    tid = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO theses(id,candidate_id,thesis,status,generated_by)
        VALUES(?,?,?,'PENDING',?)
        """,
        (tid,candidate_id,thesis,generated_by),
    )
    conn.commit()
    return tid


def confirm_thesis(conn: sqlite3.Connection, thesis_id: str) -> None:
    conn.execute(
        "UPDATE theses SET status='CONFIRMED',confirmed_at=CURRENT_TIMESTAMP WHERE id=?",
        (thesis_id,),
    )
    conn.commit()


def draft_article(conn: sqlite3.Connection, thesis_id: str) -> str:
    thesis = conn.execute("SELECT * FROM theses WHERE id=?", (thesis_id,)).fetchone()
    if not thesis:
        raise KeyError("thesis not found")
    if thesis["status"] != "CONFIRMED":
        raise ValueError("thesis must be confirmed before drafting")
    material = _candidate_material(conn, thesis["candidate_id"])
    payload = {"thesis": dict(thesis), **material}
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
    return aid


def challenge_article(conn: sqlite3.Connection, article_id: str) -> str:
    article = conn.execute("SELECT * FROM articles WHERE id=?", (article_id,)).fetchone()
    if not article:
        raise KeyError("article not found")
    material = _candidate_material(conn, article["candidate_id"])
    payload = {"article": dict(article), **material}
    data, model = chat_json("CRITIC_MODEL", CRITIC_SYSTEM, json.dumps(payload, ensure_ascii=False))
    review_id = uuid.uuid4().hex
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
            data.get("verdict",""),
            model,
        ),
    )
    conn.commit()
    return review_id
