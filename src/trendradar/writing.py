from __future__ import annotations

import json
import sqlite3
import uuid

from .content import ensure_document_for_article
from .grounding import assert_no_new_numeric_claims
from .llm import chat_json
from .prompts import CRITIC_SYSTEM, RESEARCH_SYSTEM, THESIS_SYSTEM, WRITER_SYSTEM



def _normalize_research_items(raw: object, allowed_ids: set[str], kind: str) -> list[dict]:
    items: list[dict] = []
    if not isinstance(raw, list):
        return items
    for entry in raw:
        if isinstance(entry, str):
            text = entry.strip()
            evidence_ids: list[str] = []
            note = ""
        elif isinstance(entry, dict):
            text = str(entry.get("text") or "").strip()
            raw_ids = entry.get("evidence_ids") or []
            if isinstance(raw_ids, str):
                raw_ids = [raw_ids]
            evidence_ids = [
                str(value) for value in raw_ids
                if str(value) in allowed_ids
            ] if isinstance(raw_ids, list) else []
            evidence_ids = list(dict.fromkeys(evidence_ids))
            note = str(entry.get("note") or "").strip()
        else:
            continue
        if not text:
            continue
        # FACT/CLAIM without a traceable source are not allowed to enter the
        # durable research pack. INFER may survive without ids, but is visibly
        # classified as inference rather than evidence.
        if kind in {"FACT","CLAIM"} and not evidence_ids:
            continue
        items.append({
            "text": text,
            "evidence_ids": evidence_ids,
            "note": note,
        })
    return items


def _grounding_summary(items_by_kind: dict[str, list[dict]]) -> dict:
    grounded_units = 0
    evidence_ids: set[str] = set()
    for kind, items in items_by_kind.items():
        for item in items:
            ids = {str(x) for x in item.get("evidence_ids") or []}
            if ids:
                grounded_units += 1
                evidence_ids.update(ids)
    return {
        "grounded_units": grounded_units,
        "evidence_ids": sorted(evidence_ids),
        "evidence_count": len(evidence_ids),
    }


def _persist_research_items(
    conn: sqlite3.Connection,
    research_id: str,
    candidate_id: str,
    items_by_kind: dict[str, list[dict]],
) -> None:
    for kind, items in items_by_kind.items():
        for item in items:
            item_id = uuid.uuid4().hex
            conn.execute(
                """
                INSERT INTO research_items(id,research_id,candidate_id,kind,text,note)
                VALUES(?,?,?,?,?,?)
                """,
                (item_id,research_id,candidate_id,kind,item["text"],item.get("note","")),
            )
            for intelligence_id in item.get("evidence_ids") or []:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO research_item_sources(research_item_id,intelligence_id)
                    VALUES(?,?)
                    """,
                    (item_id,intelligence_id),
                )


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
    items_by_kind = {
        "FACT": data.get("facts") or [],
        "CLAIM": data.get("claims") or [],
        "INFER": data.get("inferences") or [],
    }
    data["grounding"] = _grounding_summary(items_by_kind)
    return data


def research_candidate(conn: sqlite3.Connection, candidate_id: str) -> str:
    material = candidate_material(conn, candidate_id)
    data, model = chat_json(
        "RESEARCH_MODEL", RESEARCH_SYSTEM, json.dumps(material, ensure_ascii=False),
        conn=conn, task="research"
    )

    allowed_ids = {str(item["id"]) for item in material["evidence"]}
    items_by_kind = {
        "FACT": _normalize_research_items(data.get("facts"), allowed_ids, "FACT"),
        "CLAIM": _normalize_research_items(data.get("claims"), allowed_ids, "CLAIM"),
        "INFER": _normalize_research_items(data.get("inferences"), allowed_ids, "INFER"),
    }
    grounding = _grounding_summary(items_by_kind)

    evidence_gap = str(data.get("evidence_gap") or "").strip()
    dropped_note = ""
    raw_grounded = sum(
        len(data.get(key) or []) if isinstance(data.get(key), list) else 0
        for key in ("facts","claims")
    )
    kept_grounded = len(items_by_kind["FACT"]) + len(items_by_kind["CLAIM"])
    if raw_grounded > kept_grounded:
        dropped_note = "研究模型返回了无法追溯到输入 evidence id 的事实/主张，系统已自动丢弃。"
    if grounding["evidence_count"] < 2:
        insuff = "当前研究包尚未形成两个独立 evidence id 的交叉支撑。"
        dropped_note = f"{dropped_note} {insuff}".strip()
    evidence_gap = f"{evidence_gap} {dropped_note}".strip()

    rid = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO research(id,candidate_id,facts_json,claims_json,inferences_json,strongest_counter,evidence_gap,generated_by)
        VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            rid,candidate_id,
            json.dumps(items_by_kind["FACT"],ensure_ascii=False),
            json.dumps(items_by_kind["CLAIM"],ensure_ascii=False),
            json.dumps(items_by_kind["INFER"],ensure_ascii=False),
            data.get("strongest_counter",""),
            evidence_gap,
            model,
        ),
    )
    _persist_research_items(conn,rid,candidate_id,items_by_kind)
    conn.commit()
    return rid


def propose_thesis(conn: sqlite3.Connection, candidate_id: str) -> str:
    research = latest_research(conn, candidate_id)
    if not research:
        raise ValueError("research is required before thesis")
    grounding = research.get("grounding") or {}
    if int(grounding.get("grounded_units") or 0) < 2 or int(grounding.get("evidence_count") or 0) < 2:
        raise ValueError("research requires at least 2 grounded units from 2 evidence items before thesis")
    material = candidate_material(conn, candidate_id)
    data, model = chat_json(
        "RESEARCH_MODEL",
        THESIS_SYSTEM,
        json.dumps({"research": research, **material}, ensure_ascii=False),
        conn=conn,
        task="thesis",
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
    data, model = chat_json(
        "WRITING_MODEL", WRITER_SYSTEM, json.dumps(payload, ensure_ascii=False),
        conn=conn, task="writer"
    )
    generated_title = str(data.get("title") or "")
    generated_body = str(data.get("body") or "")
    allowed_numeric_texts = [
        str(material.get("candidate") or {}),
        json.dumps(research or {},ensure_ascii=False),
        *(f"{e.get('title','')} {e.get('summary','')} {e.get('content','')}" for e in material.get("evidence",[])),
        thesis["thesis"],
    ]
    assert_no_new_numeric_claims(
        f"{generated_title}\n{generated_body}",
        allowed_numeric_texts,
        context="writer",
    )

    aid = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO articles(id,candidate_id,thesis_id,title,outline,body,status,generated_by)
        VALUES(?,?,?,?,?,?,'CHALLENGE',?)
        """,
        (
            aid,thesis["candidate_id"],thesis_id,
            generated_title,
            json.dumps(data.get("outline",[]),ensure_ascii=False),
            generated_body,
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
    data, model = chat_json(
        "CRITIC_MODEL", CRITIC_SYSTEM, json.dumps(payload, ensure_ascii=False),
        conn=conn, task="critic"
    )
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
