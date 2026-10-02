"""Opportunity Engine: one ANALYSIS call per gated pain cluster → grounded PainSignals + Opportunity +
explainable scores + evidence + graph edges. Each pain cluster owns at most one opportunity; re-runs
update it in place (version++, scores refreshed, human status preserved)."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from ..clustering.pain_clusters import cluster_signals
from ..core.ids import stable_id
from ..core.logging import get_logger
from ..core.timeutil import iso, parse_datetime, utcnow
from ..graph.edges import add_edge
from ..market.competition import load_competition_profile
from ..providers.llm import resolve_llm
from ..scoring.dimensions import (
    DEFAULT_WEIGHTS,
    SCORING_VERSION,
    DimensionScore,
    competition_score,
    demand_score,
    evidence_confidence,
    final_score,
    growth_score,
    judgement_dimension,
)
from ..trends.velocity import series, velocity_metrics
from .grounding import ground_quote, keep_known_ids

log = get_logger("opportunities")

ANALYZE_SYSTEM = """You are a rigorous product strategist analysing a cluster of user complaints for a software opportunity radar serving indie developers and small SaaS teams in the global market.

You receive: the cluster, its signals (each with an id), comparable existing products (each with an id, plus derived pros/cons/complaints), and trend metrics. Use ONLY this material. Never invent products, quotes or facts.

Return JSON with exactly this shape:
{
 "label": "≤12-word problem statement",
 "summary": "2–3 sentences: who, what problem, current workarounds",
 "persona": "developer|designer|marketer|freelancer|startup_founder|small_business_owner|ecommerce_seller|agency|consumer|other",
 "category": "developer_tools|ai_tools|productivity|finance|small_business|marketing|ecommerce|design|other",
 "pain_signals": [ {"signal_id": "<id from input>", "problem": "...", "context": "...", "severity": 0-100, "frequency": 0-100, "willingness_to_pay": 0-100, "existing_workaround": "...", "current_solution": "...", "friction": ["expensive|slow|complicated|fragmented|unreliable|repetitive|poor_ux|missing_feature"], "evidence_quote": "verbatim short quote copied from that signal"} ],
 "opportunity": {"title": "product-style name ≤6 words", "description": "...", "target_user": "...", "core_pain": "...", "proposed_solution": "...", "wedge": "the specific entry point vs existing products", "monetization": "...", "distribution": "...", "build_type": "web|mac|chrome_extension|cli|api|mobile|plugin|desktop", "build_difficulty": "weekend|2_weeks|1_3_months|3_plus_months", "why_now": "...", "competitor_weakness": "...", "risks": ["..."], "next_action": "concrete next step for validation"},
 "scores": {
   "pain": {"score": 0-100, "reason": "...", "evidence_ids": ["<signal ids>"]},
   "gap": {"score": 0-100, "reason": "...", "evidence_ids": ["<signal or product ids>"]},
   "monetization": {"score": 0-100, "reason": "...", "evidence_ids": []},
   "build_ease": {"score": 0-100 (higher = easier), "reason": "...", "evidence_ids": []},
   "distribution": {"score": 0-100, "reason": "...", "evidence_ids": []}
 }
}
Be conservative: if the evidence is thin, say so in reasons and score lower. A market with zero competitors is not automatically attractive."""


class PainSignalOut(BaseModel):
    signal_id: str
    problem: str
    context: str | None = None
    severity: float | None = Field(default=None, ge=0, le=100)
    frequency: float | None = Field(default=None, ge=0, le=100)
    willingness_to_pay: float | None = Field(default=None, ge=0, le=100)
    existing_workaround: str | None = None
    current_solution: str | None = None
    friction: list[str] = Field(default_factory=list)
    evidence_quote: str | None = None


class OpportunityOut(BaseModel):
    title: str
    description: str | None = None
    target_user: str | None = None
    core_pain: str | None = None
    proposed_solution: str | None = None
    wedge: str | None = None
    monetization: str | None = None
    distribution: str | None = None
    build_type: str | None = None
    build_difficulty: str | None = None
    why_now: str | None = None
    competitor_weakness: str | None = None
    risks: list[str] = Field(default_factory=list)
    next_action: str | None = None


class ScoreOut(BaseModel):
    score: float | None = Field(default=None, ge=0, le=100)
    reason: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class AnalysisOut(BaseModel):
    label: str | None = None
    summary: str | None = None
    persona: str | None = None
    category: str | None = None
    pain_signals: list[PainSignalOut] = Field(default_factory=list)
    opportunity: OpportunityOut
    scores: dict[str, ScoreOut] = Field(default_factory=dict)


# ───────────────────────── payload ─────────────────────────


def build_analysis_payload(
    conn: sqlite3.Connection, cluster: sqlite3.Row, *, signal_limit: int = 12
) -> tuple[dict, dict[str, dict], dict[str, dict]]:
    signals = cluster_signals(conn, cluster["id"], signal_limit)
    profile = load_competition_profile(conn, cluster["id"]) or {}
    competitors: dict[str, dict] = {}
    for c in profile.get("competitors", []):
        row = conn.execute(
            "SELECT id, external_id, name, tagline, description, votes, rating, review_count, pricing, pricing_origin, launched_at, url, origin FROM products WHERE id=?",
            (c["product_id"],),
        ).fetchone()
        if row is None:
            continue
        ins = conn.execute(
            "SELECT pros_json, cons_json, complaints_json, review_summary FROM product_insights WHERE product_id=?",
            (row["id"],),
        ).fetchone()
        competitors[row["id"]] = {
            **dict(row),
            "pros": json.loads(ins["pros_json"]) if ins else [],
            "cons": json.loads(ins["cons_json"]) if ins else [],
            "complaints": json.loads(ins["complaints_json"]) if ins else [],
            "review_summary": ins["review_summary"] if ins else None,
        }
    metrics = velocity_metrics(series(conn, "pain_cluster", cluster["id"]))
    payload = {
        "cluster": {
            "id": cluster["id"],
            "label": cluster["label"],
            "summary": cluster["summary"],
            "persona": cluster["persona"],
            "category": cluster["category"],
            "signal_count": cluster["signal_count"],
            "unique_users": cluster["unique_users"],
            "source_count": cluster["source_count"],
            "stage": cluster["stage"],
            "velocity": cluster["velocity"],
        },
        "signals": [
            {
                "id": s["id"],
                "external_id": s["external_id"],
                "source": s["source_id"],
                "title": s["title"],
                "content": s["content"][:1500],
                "created_at": s["created_at"],
                "engagement": json.loads(s["engagement_json"] or "{}"),
            }
            for s in signals
        ],
        "competitors": [
            {k: v for k, v in c.items() if k != "description"}
            | {"description": (c.get("description") or "")[:400]}
            for c in competitors.values()
        ],
        "competition": {
            k: profile.get(k)
            for k in (
                "density",
                "maturity",
                "avg_rating",
                "review_volume",
                "recent_launches_90d",
                "competitor_count",
                "common_complaints",
                "pricing_distribution",
            )
        },
        "trend": metrics,
    }
    return payload, {s["id"]: s for s in signals}, competitors


# ───────────────────────── persistence ─────────────────────────


def _upsert_pain_signals(
    conn: sqlite3.Connection,
    cluster_id: str,
    items: list[PainSignalOut],
    signals: dict[str, dict],
    model: str,
) -> tuple[int, int]:
    written = dropped = 0
    for ps in items:
        src = signals.get(ps.signal_id)
        if src is None:
            dropped += 1
            continue
        quote, grounded = ground_quote(ps.evidence_quote, f"{src['title']}\n{src['content']}")
        conn.execute(
            """INSERT INTO pain_signals(id,signal_id,cluster_id,problem,persona,context,severity,frequency,willingness_to_pay,existing_workaround,current_solution,friction_json,evidence_quote,confidence,generated_by)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(signal_id) DO UPDATE SET cluster_id=excluded.cluster_id,problem=excluded.problem,context=excluded.context,severity=excluded.severity,
               frequency=excluded.frequency,willingness_to_pay=excluded.willingness_to_pay,existing_workaround=excluded.existing_workaround,current_solution=excluded.current_solution,
               friction_json=excluded.friction_json,evidence_quote=excluded.evidence_quote,confidence=excluded.confidence,generated_by=excluded.generated_by""",
            (
                stable_id("pain", ps.signal_id),
                ps.signal_id,
                cluster_id,
                ps.problem[:600],
                None,
                (ps.context or "")[:400] or None,
                ps.severity,
                ps.frequency,
                ps.willingness_to_pay,
                (ps.existing_workaround or "")[:300] or None,
                (ps.current_solution or "")[:300] or None,
                json.dumps(ps.friction[:6]),
                quote,
                0.8 if grounded else 0.5,
                model,
            ),
        )
        written += 1
    return written, dropped


def _write_evidence(
    conn: sqlite3.Connection,
    opportunity_id: str,
    cluster_id: str,
    signals: dict[str, dict],
    competitors: dict[str, dict],
) -> int:
    conn.execute("DELETE FROM evidence WHERE subject_type='opportunity' AND subject_id=?", (opportunity_id,))
    n = 0
    for sid, s in signals.items():
        ps = conn.execute(
            "SELECT evidence_quote, problem FROM pain_signals WHERE signal_id=?", (sid,)
        ).fetchone()
        quote = (ps["evidence_quote"] if ps and ps["evidence_quote"] else None) or (
            s["content"][:240] + ("…" if len(s["content"]) > 240 else "")
        )
        conn.execute(
            "INSERT INTO evidence(id,subject_type,subject_id,kind,signal_id,source_id,quote,url,occurred_at,origin) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                stable_id("ev", opportunity_id, sid),
                "opportunity",
                opportunity_id,
                "pain",
                sid,
                s["source_id"],
                quote,
                s["url"],
                s["created_at"],
                s["origin"],
            ),
        )
        add_edge(conn, "opportunity", opportunity_id, "supported_by", "signal", sid)
        n += 1
    for pid, c in competitors.items():
        for complaint in (c.get("complaints") or [])[:3]:
            conn.execute(
                "INSERT INTO evidence(id,subject_type,subject_id,kind,product_id,source_id,quote,url,origin) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    stable_id("ev", opportunity_id, pid, complaint),
                    "opportunity",
                    opportunity_id,
                    "complaint",
                    pid,
                    "producthunt",
                    complaint,
                    c["url"],
                    c["origin"],
                ),
            )
            n += 1
        conn.execute(
            "INSERT OR IGNORE INTO evidence(id,subject_type,subject_id,kind,product_id,source_id,quote,url,origin) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                stable_id("ev", opportunity_id, pid, "competitor"),
                "opportunity",
                opportunity_id,
                "competitor",
                pid,
                "producthunt",
                f"{c['name']} — {c.get('tagline') or ''}",
                c["url"],
                c["origin"],
            ),
        )
        add_edge(conn, "opportunity", opportunity_id, "competes_with", "product", pid, weight=1.0)
        n += 1
    return n


def _score(
    conn: sqlite3.Connection,
    cluster: sqlite3.Row,
    analysis: AnalysisOut | None,
    model: str | None,
    signals: dict[str, dict],
    competitors: dict[str, dict],
    weights: dict[str, float],
) -> dict[str, DimensionScore]:
    profile = load_competition_profile(conn, cluster["id"]) or {}
    engagement_total = 0
    for s in signals.values():
        e = json.loads(s["engagement_json"] or "{}")
        engagement_total += int(e.get("votes", 0)) + int(e.get("comments", 0))
    metrics = velocity_metrics(series(conn, "pain_cluster", cluster["id"]))
    signal_ids = list(signals.keys())
    last_seen = parse_datetime(cluster["last_seen"])
    days_since_last = (utcnow() - last_seen).total_seconds() / 86400 if last_seen else 30.0
    allowed = set(signal_ids) | set(competitors.keys())
    dims: dict[str, DimensionScore] = {
        "demand": demand_score(
            signal_count=int(cluster["signal_count"]),
            unique_users=int(cluster["unique_users"]),
            source_count=int(cluster["source_count"]),
            engagement_total=engagement_total,
            evidence_ids=signal_ids,
        ),
        "growth": growth_score(
            velocity=float(cluster["velocity"] or 0),
            acceleration=float(cluster["acceleration"] or 0),
            stage=cluster["stage"],
            recent_7d=metrics["recent_7d"],
        ),
        "competition": competition_score(
            competitor_count=int(profile.get("competitor_count") or 0),
            density=float(profile.get("density") or 0),
            maturity=float(profile.get("maturity") or 0),
            avg_rating=profile.get("avg_rating"),
            complaint_count=len(profile.get("common_complaints") or []),
            evidence_ids=list(competitors.keys()),
        ),
        "confidence": evidence_confidence(
            signal_count=int(cluster["signal_count"]),
            source_count=int(cluster["source_count"]),
            unique_users=int(cluster["unique_users"]),
            days_since_last=days_since_last,
            data_mode=cluster["data_mode"],
            model_available=analysis is not None,
        ),
    }
    for name in ("pain", "gap", "monetization", "build_ease", "distribution"):
        payload = None
        if analysis and name in analysis.scores:
            score_out = analysis.scores[name]
            payload = {
                "score": score_out.score,
                "reason": score_out.reason,
                "evidence_ids": keep_known_ids(score_out.evidence_ids, allowed),
            }
        dims[name] = judgement_dimension(name, payload, model_name=model)
    return dims


# ───────────────────────── main entry ─────────────────────────


def analyze_cluster(
    conn: sqlite3.Connection,
    cluster_id: str,
    *,
    weights: dict[str, float] | None = None,
    job_id: str | None = None,
    session_id: str | None = None,
) -> dict:
    cluster = conn.execute("SELECT * FROM pain_clusters WHERE id=?", (cluster_id,)).fetchone()
    if cluster is None:
        return {"ok": False, "reason": "cluster not found"}
    payload, signals, competitors = build_analysis_payload(conn, cluster)
    provider = resolve_llm("ANALYSIS_MODEL", cluster["data_mode"])
    analysis: AnalysisOut | None = None
    model: str | None = None
    if provider is None:
        reason = "ANALYSIS_MODEL not configured — live clusters are never analysed with canned answers"
        conn.execute(
            "UPDATE pain_clusters SET analysis_status='skipped', analysis_error=? WHERE id=?",
            (reason, cluster_id),
        )
        conn.commit()
        return {"ok": False, "reason": reason}
    try:
        raw, model = provider.chat_json(
            "ANALYSIS_MODEL",
            ANALYZE_SYSTEM,
            json.dumps(payload, ensure_ascii=False),
            task="analyze_cluster",
            conn=conn,
            timeout=180,
            job_id=job_id,
        )
        if not isinstance(raw, dict) or raw.get("error"):
            raise ValueError(str(raw.get("error") if isinstance(raw, dict) else "non-object response"))
        analysis = AnalysisOut.model_validate(raw)
    except (ValidationError, ValueError, RuntimeError) as exc:
        conn.execute(
            "UPDATE pain_clusters SET analysis_status='failed', analysis_error=? WHERE id=?",
            (str(exc)[:500], cluster_id),
        )
        conn.commit()
        log.warning("analysis failed for %s: %s", cluster_id, exc)
        return {"ok": False, "reason": str(exc)[:300]}

    generated_by = "fixture" if model == "fixture" else (model or "model")
    written, dropped = _upsert_pain_signals(conn, cluster_id, analysis.pain_signals, signals, generated_by)
    conn.execute(
        "UPDATE pain_clusters SET label=COALESCE(?,label), summary=COALESCE(?,summary), persona=COALESCE(?,persona), category=COALESCE(?,category), label_source=?, analysis_status='done', analysis_error=NULL, updated_at=? WHERE id=?",
        (
            (analysis.label or "")[:200] or None,
            analysis.summary,
            analysis.persona,
            analysis.category,
            generated_by,
            iso(utcnow()),
            cluster_id,
        ),
    )
    cluster = conn.execute("SELECT * FROM pain_clusters WHERE id=?", (cluster_id,)).fetchone()

    opportunity_id = stable_id("opportunity", cluster_id)
    existing = conn.execute(
        "SELECT id, status, version, first_seen FROM opportunities WHERE id=?", (opportunity_id,)
    ).fetchone()
    dims = _score(conn, cluster, analysis, model, signals, competitors, weights or DEFAULT_WEIGHTS)
    score, confidence = final_score(dims, weights or DEFAULT_WEIGHTS)
    o = analysis.opportunity
    data_mode = cluster["data_mode"]
    if competitors and data_mode == "live" and any(c["origin"] == "mock" for c in competitors.values()):
        data_mode = "mixed"
    now = iso(utcnow())
    if existing:
        conn.execute(
            """UPDATE opportunities SET title=?,description=?,target_user=?,core_pain=?,proposed_solution=?,wedge=?,monetization=?,distribution=?,build_type=?,build_difficulty=?,
               why_now=?,competitor_weakness=?,risks_json=?,next_action=?,opportunity_score=?,confidence=?,data_mode=?,version=version+1,last_seen=?,signal_count=?,growth=?,generated_by=?,updated_at=? WHERE id=?""",
            (
                o.title[:120],
                o.description,
                o.target_user,
                o.core_pain,
                o.proposed_solution,
                o.wedge,
                o.monetization,
                o.distribution,
                o.build_type,
                o.build_difficulty,
                o.why_now,
                o.competitor_weakness,
                json.dumps(o.risks[:6], ensure_ascii=False),
                o.next_action,
                score,
                confidence,
                data_mode,
                cluster["last_seen"] or now,
                int(cluster["signal_count"]),
                float(cluster["velocity"] or 0),
                generated_by,
                now,
                opportunity_id,
            ),
        )
    else:
        conn.execute(
            """INSERT INTO opportunities(id,pain_cluster_id,title,description,target_user,core_pain,proposed_solution,wedge,monetization,distribution,build_type,build_difficulty,
               why_now,competitor_weakness,risks_json,next_action,status,opportunity_score,confidence,data_mode,version,first_seen,last_seen,signal_count,growth,generated_by,session_id)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'discovered',?,?,?,1,?,?,?,?,?,?)""",
            (
                opportunity_id,
                cluster_id,
                o.title[:120],
                o.description,
                o.target_user,
                o.core_pain,
                o.proposed_solution,
                o.wedge,
                o.monetization,
                o.distribution,
                o.build_type,
                o.build_difficulty,
                o.why_now,
                o.competitor_weakness,
                json.dumps(o.risks[:6], ensure_ascii=False),
                o.next_action,
                score,
                confidence,
                data_mode,
                cluster["first_seen"] or now,
                cluster["last_seen"] or now,
                int(cluster["signal_count"]),
                float(cluster["velocity"] or 0),
                generated_by,
                session_id,
            ),
        )
        conn.execute(
            "INSERT INTO opportunity_status_log(opportunity_id,from_status,to_status,note) VALUES(?,?,?,?)",
            (opportunity_id, None, "discovered", "generated"),
        )
    conn.execute("DELETE FROM opportunity_scores WHERE opportunity_id=?", (opportunity_id,))
    for d in dims.values():
        conn.execute(
            "INSERT INTO opportunity_scores(opportunity_id,dimension,score,reason,confidence,evidence_ids_json,method,scoring_version) VALUES(?,?,?,?,?,?,?,?)",
            (
                opportunity_id,
                d.dimension,
                round(d.score, 1),
                d.reason,
                d.confidence,
                json.dumps(d.evidence_ids),
                d.method,
                SCORING_VERSION,
            ),
        )
    evidence_count = _write_evidence(conn, opportunity_id, cluster_id, signals, competitors)
    add_edge(conn, "opportunity", opportunity_id, "derived_from", "pain_cluster", cluster_id)
    if cluster["persona"]:
        conn.execute(
            "INSERT OR IGNORE INTO personas(id,name) VALUES(?,?)",
            (stable_id("persona", cluster["persona"]), cluster["persona"]),
        )
        add_edge(
            conn, "pain_cluster", cluster_id, "affects", "persona", stable_id("persona", cluster["persona"])
        )
    if cluster["category"]:
        add_edge(conn, "opportunity", opportunity_id, "belongs_to", "category", cluster["category"])
    conn.commit()
    return {
        "ok": True,
        "opportunity_id": opportunity_id,
        "score": score,
        "confidence": confidence,
        "pain_signals": written,
        "dropped_pain_signals": dropped,
        "evidence": evidence_count,
        "model": model,
    }


def rescore(
    conn: sqlite3.Connection, opportunity_id: str, *, weights: dict[str, float] | None = None
) -> dict[str, Any]:
    """Recompute deterministic dimensions (demand/growth/competition/confidence) without a model call."""
    opp = conn.execute("SELECT * FROM opportunities WHERE id=?", (opportunity_id,)).fetchone()
    if opp is None:
        return {}
    cluster = conn.execute("SELECT * FROM pain_clusters WHERE id=?", (opp["pain_cluster_id"],)).fetchone()
    _, signals, competitors = build_analysis_payload(conn, cluster)
    existing = {
        r["dimension"]: r
        for r in conn.execute("SELECT * FROM opportunity_scores WHERE opportunity_id=?", (opportunity_id,))
    }
    dims = _score(conn, cluster, None, None, signals, competitors, weights or DEFAULT_WEIGHTS)
    for name in ("pain", "gap", "monetization", "build_ease", "distribution"):
        if name in existing and existing[name]["method"] != "unavailable":
            r = existing[name]
            dims[name] = DimensionScore(
                name,
                r["score"],
                r["reason"],
                r["confidence"],
                json.loads(r["evidence_ids_json"]),
                r["method"],
            )
    dims["confidence"] = evidence_confidence(
        signal_count=int(cluster["signal_count"]),
        source_count=int(cluster["source_count"]),
        unique_users=int(cluster["unique_users"]),
        days_since_last=0.0,
        data_mode=cluster["data_mode"],
        model_available=any(d.method in ("model", "fixture") for d in dims.values()),
    )
    score, confidence = final_score(dims, weights or DEFAULT_WEIGHTS)
    conn.execute("DELETE FROM opportunity_scores WHERE opportunity_id=?", (opportunity_id,))
    for d in dims.values():
        conn.execute(
            "INSERT INTO opportunity_scores(opportunity_id,dimension,score,reason,confidence,evidence_ids_json,method,scoring_version) VALUES(?,?,?,?,?,?,?,?)",
            (
                opportunity_id,
                d.dimension,
                round(d.score, 1),
                d.reason,
                d.confidence,
                json.dumps(d.evidence_ids),
                d.method,
                SCORING_VERSION,
            ),
        )
    conn.execute(
        "UPDATE opportunities SET opportunity_score=?, confidence=?, signal_count=?, growth=?, last_seen=?, updated_at=? WHERE id=?",
        (
            score,
            confidence,
            int(cluster["signal_count"]),
            float(cluster["velocity"] or 0),
            cluster["last_seen"],
            iso(utcnow()),
            opportunity_id,
        ),
    )
    conn.commit()
    return {"score": score, "confidence": confidence}
