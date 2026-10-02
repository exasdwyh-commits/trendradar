"""Ask: natural-language questions answered from the database only (no web search).

plan (FAST/fixture) → SQL filters + semantic ranking over stored opportunities → answer (ANALYSIS/fixture)
with citations to opportunity ids. If nothing matches, the answer says so.
"""

from __future__ import annotations

import json
import sqlite3

from ..clustering.index import normalize
from ..core.ids import new_id
from ..core.timeutil import iso, utcnow
from ..providers.embeddings import from_blob, get_embedder
from ..providers.llm import resolve_llm

PLAN_SYSTEM = """Turn a user question about software opportunities into a JSON retrieval plan for a local database. Fields (all optional):
category (developer_tools|ai_tools|productivity|finance|small_business|marketing|ecommerce|design|other), persona, build_difficulty (list of weekend|2_weeks|1_3_months|3_plus_months), build_type (list of web|mac|chrome_extension|cli|api|mobile|plugin|desktop), min_score (0-100), status (list), sort (opportunity_score|growth|last_seen), limit (1-10), keywords (list of short strings).
Return only JSON."""

ANSWER_SYSTEM = """You answer questions for an indie developer using ONLY the opportunities and evidence provided (they come from the user's own database). Do not use outside knowledge, do not invent products or numbers.
Write concise markdown. Reference opportunities inline as [opp:<id>] right after their title so the UI can link them. If the material does not answer the question, say so plainly.
Return JSON: {"answer_md": "...", "citations": ["<opportunity ids used>"]}"""


def _plan(conn: sqlite3.Connection, question: str, data_mode: str) -> tuple[dict, str | None]:
    provider = resolve_llm("FAST_MODEL", data_mode)
    if provider is None:
        return {
            "limit": 5,
            "sort": "opportunity_score",
            "keywords": [w for w in question.lower().split() if len(w) > 3][:6],
        }, None
    try:
        data, model = provider.chat_json(
            "FAST_MODEL", PLAN_SYSTEM, json.dumps({"question": question}), task="ask_plan", conn=conn
        )
        return (data if isinstance(data, dict) else {}), model
    except Exception:
        return {"limit": 5, "sort": "opportunity_score"}, None


def _retrieve(conn: sqlite3.Connection, question: str, plan: dict) -> list[dict]:
    where = ["o.session_id IS NULL", "o.status NOT IN ('rejected','archived')"]
    params: list = []
    if plan.get("category"):
        where.append("pc.category=?")
        params.append(plan["category"])
    if plan.get("persona"):
        where.append("pc.persona=?")
        params.append(plan["persona"])
    for key in ("build_difficulty", "build_type", "status"):
        vals = plan.get(key)
        if isinstance(vals, str):
            vals = [vals]
        if vals:
            where.append(f"o.{key} IN ({','.join('?' * len(vals))})")
            params.extend(vals)
    if plan.get("min_score"):
        where.append("o.opportunity_score>=?")
        params.append(float(plan["min_score"]))
    sort = (
        plan.get("sort")
        if plan.get("sort") in ("opportunity_score", "growth", "last_seen")
        else "opportunity_score"
    )
    rows = conn.execute(
        f"""SELECT o.*, pc.persona, pc.category, pc.stage, pc.velocity, pc.centroid, pc.centroid_model FROM opportunities o
            JOIN pain_clusters pc ON pc.id=o.pain_cluster_id WHERE {" AND ".join(where)} ORDER BY o.{sort} DESC LIMIT 40""",
        params,
    ).fetchall()
    if not rows and (
        plan.get("category") or plan.get("persona") or plan.get("build_difficulty") or plan.get("build_type")
    ):
        # relax structured filters, keep semantic ranking
        rows = conn.execute(
            "SELECT o.*, pc.persona, pc.category, pc.stage, pc.velocity, pc.centroid, pc.centroid_model FROM opportunities o JOIN pain_clusters pc ON pc.id=o.pain_cluster_id WHERE o.session_id IS NULL AND o.status NOT IN ('rejected','archived') ORDER BY o.opportunity_score DESC LIMIT 40"
        ).fetchall()
    embedder = get_embedder()
    q = normalize(embedder.embed([question])[0])
    keywords = [k.lower() for k in (plan.get("keywords") or []) if isinstance(k, str)]
    scored = []
    for r in rows:
        sim = 0.0
        if r["centroid"] is not None and r["centroid_model"] == embedder.name:
            sim = float(q @ normalize(from_blob(r["centroid"], len(q))))
        text = f"{r['title']} {r['core_pain'] or ''} {r['description'] or ''}".lower()
        kw = sum(1 for k in keywords if k in text)
        scored.append((sim + 0.05 * kw + float(r["opportunity_score"] or 0) / 400, r))
    scored.sort(key=lambda x: -x[0])
    limit = int(plan.get("limit") or 5)
    out = []
    for _, r in scored[: max(1, min(limit, 10))]:
        d = {
            k: r[k]
            for k in (
                "id",
                "title",
                "description",
                "core_pain",
                "proposed_solution",
                "wedge",
                "target_user",
                "build_type",
                "build_difficulty",
                "monetization",
                "opportunity_score",
                "confidence",
                "status",
                "data_mode",
                "persona",
                "category",
                "stage",
                "signal_count",
            )
        }
        d["evidence"] = [
            dict(e)
            for e in conn.execute(
                "SELECT quote, url, source_id, origin FROM evidence WHERE subject_type='opportunity' AND subject_id=? AND kind='pain' LIMIT 3",
                (r["id"],),
            )
        ]
        out.append(d)
    return out


def ask(conn: sqlite3.Connection, question: str) -> dict:
    modes = [
        r[0] for r in conn.execute("SELECT DISTINCT data_mode FROM opportunities WHERE session_id IS NULL")
    ]
    data_mode = (
        "live"
        if modes and all(m == "live" for m in modes)
        else "mock"
        if modes and all(m == "mock" for m in modes)
        else "mixed"
        if modes
        else "mock"
    )
    plan, plan_model = _plan(conn, question, data_mode)
    candidates = _retrieve(conn, question, plan)
    provider = resolve_llm("ANALYSIS_MODEL", data_mode)
    if provider is None:
        answer_md = (
            "ANALYSIS_MODEL is not configured, so this answer is a plain list of the best-matching opportunities from the database:\n\n"
            + "\n".join(
                f"- **{c['title']}** [opp:{c['id']}] — score {c['opportunity_score']:.0f}: {c['core_pain'] or ''}"
                for c in candidates
            )
            if candidates
            else "No opportunities in the database match this question yet."
        )
        citations, model = [c["id"] for c in candidates], None
    else:
        payload = {"question": question, "opportunities": candidates}
        try:
            data, model = provider.chat_json(
                "ANALYSIS_MODEL",
                ANSWER_SYSTEM,
                json.dumps(payload, ensure_ascii=False),
                task="ask_answer",
                conn=conn,
                timeout=120,
            )
            answer_md = (
                str(data.get("answer_md") or "").strip()
                or "No answer could be produced from the stored evidence."
            )
            known = {c["id"] for c in candidates}
            citations = [c for c in (data.get("citations") or []) if c in known] or [
                c["id"] for c in candidates if f"[opp:{c['id']}]" in answer_md
            ]
        except Exception as exc:
            answer_md, citations, model = (
                f"The analysis model failed ({exc}). Best-matching opportunities:\n\n"
                + "\n".join(f"- **{c['title']}** [opp:{c['id']}]" for c in candidates),
                [c["id"] for c in candidates],
                None,
            )
    session_id = new_id()
    conn.execute(
        "INSERT INTO ask_sessions(id,question,plan_json,answer_md,citations_json,generated_by) VALUES(?,?,?,?,?,?)",
        (session_id, question, json.dumps(plan), answer_md, json.dumps(citations), model or "database"),
    )
    conn.commit()
    return {
        "id": session_id,
        "question": question,
        "plan": plan,
        "answer_md": answer_md,
        "citations": citations,
        "candidates": [
            {k: c[k] for k in ("id", "title", "opportunity_score", "confidence", "data_mode", "status")}
            for c in candidates
        ],
        "generated_by": model or "database",
        "data_mode": data_mode,
        "created_at": iso(utcnow()),
    }
