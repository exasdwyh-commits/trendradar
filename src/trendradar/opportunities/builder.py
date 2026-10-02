"""Start Product → Builder brief. One ANALYSIS call, grounded in the opportunity's stored evidence."""

from __future__ import annotations

import json
import sqlite3

from pydantic import BaseModel, Field, ValidationError

from ..core.errors import NotConfigured, NotFound, ValidationFailed
from ..core.ids import new_id
from ..providers.llm import resolve_llm

BRIEF_SYSTEM = """You are a pragmatic product lead writing a build brief for a solo developer / small team. Use ONLY the supplied opportunity, pain signals, competitors and evidence. Do not invent competitors, numbers or quotes.
Return JSON with exactly these keys:
{"problem_definition": "...", "target_user": "...", "jtbd": ["job statements"], "mvp_scope": "what the first shippable version does and does NOT do",
 "core_features": [{"name": "...", "priority": "must|should|later", "why": "evidence-based reason"}], "pricing_idea": "model + price points + rationale",
 "competitors": [{"name": "<from input>", "weakness": "..."}], "differentiation": "...", "technical_difficulty": "level (weekend|2_weeks|1_3_months|3_plus_months) + main risks",
 "recommended_stack": ["..."], "go_to_market": ["channel + first concrete step"], "validation_plan": ["cheap tests to run before building"]}"""


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    text = str(value).strip()
    parts = [p.strip(" -•") for p in text.replace("; ", "\n").split("\n") if p.strip(" -•")]
    return parts or [text]


class Brief(BaseModel):
    problem_definition: str
    target_user: str
    jtbd: list[str] = Field(default_factory=list)
    mvp_scope: str
    core_features: list[dict] = Field(default_factory=list)
    pricing_idea: str = ""
    competitors: list[dict] = Field(default_factory=list)
    differentiation: str = ""
    technical_difficulty: str = ""
    recommended_stack: list[str] = Field(default_factory=list)
    go_to_market: list[str] = Field(default_factory=list)
    validation_plan: list[str] = Field(default_factory=list)

    @classmethod
    def coerce(cls, data: dict) -> Brief:
        """Accept the looser shapes models (and fixtures) tend to produce."""
        d = dict(data)
        d.setdefault("problem_definition", d.pop("problem", None))
        d.setdefault("mvp_scope", d.pop("mvp", None))
        d.setdefault("core_features", d.pop("features", None))
        d.setdefault("pricing_idea", d.pop("pricing", None))
        d.setdefault("technical_difficulty", d.pop("difficulty", None))
        d.setdefault("recommended_stack", d.pop("stack", None))
        d.setdefault("go_to_market", d.pop("gtm", None))
        for key in ("jtbd", "recommended_stack", "go_to_market", "validation_plan"):
            d[key] = [str(x) for x in _as_list(d.get(key))]
        d["core_features"] = [
            x if isinstance(x, dict) else {"name": str(x), "priority": "must", "why": ""}
            for x in _as_list(d.get("core_features"))
        ]
        d["competitors"] = [
            x if isinstance(x, dict) else {"name": str(x), "weakness": ""}
            for x in _as_list(d.get("competitors"))
        ]
        for key in ("pricing_idea", "technical_difficulty", "differentiation"):
            v = d.get(key)
            d[key] = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v or "")
        return cls.model_validate(d)


def get_brief(conn: sqlite3.Connection, opportunity_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM builder_briefs WHERE opportunity_id=? ORDER BY created_at DESC LIMIT 1",
        (opportunity_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "opportunity_id": opportunity_id,
        "generated_by": row["generated_by"],
        "created_at": row["created_at"],
        **json.loads(row["content_json"]),
    }


def generate_brief(conn: sqlite3.Connection, opportunity_id: str, *, force: bool = False) -> dict:
    if not force:
        existing = get_brief(conn, opportunity_id)
        if existing:
            return existing
    opp = conn.execute(
        "SELECT o.*, pc.label cluster_label, pc.summary cluster_summary, pc.persona, pc.category FROM opportunities o JOIN pain_clusters pc ON pc.id=o.pain_cluster_id WHERE o.id=?",
        (opportunity_id,),
    ).fetchone()
    if opp is None:
        raise NotFound("opportunity not found", details={"id": opportunity_id})
    provider = resolve_llm("ANALYSIS_MODEL", opp["data_mode"])
    if provider is None:
        raise NotConfigured(
            "ANALYSIS_MODEL is not configured; builder briefs for live data require a real model."
        )
    pains = [
        dict(r)
        for r in conn.execute(
            "SELECT ps.problem, ps.existing_workaround, ps.willingness_to_pay, ps.severity, ps.evidence_quote, s.external_id, s.url FROM pain_signals ps JOIN signals s ON s.id=ps.signal_id WHERE ps.cluster_id=? LIMIT 12",
            (opp["pain_cluster_id"],),
        )
    ]
    comp = conn.execute(
        "SELECT competitors_json, common_complaints_json, pricing_distribution_json FROM competition_profiles WHERE pain_cluster_id=?",
        (opp["pain_cluster_id"],),
    ).fetchone()
    competitors = json.loads(comp["competitors_json"]) if comp else []
    for c in competitors:
        ext = conn.execute(
            "SELECT external_id, tagline, pricing FROM products WHERE id=?", (c["product_id"],)
        ).fetchone()
        if ext:
            c.update(
                {"external_id": ext["external_id"], "tagline": ext["tagline"], "pricing": ext["pricing"]}
            )
        ins = conn.execute(
            "SELECT cons_json, complaints_json FROM product_insights WHERE product_id=?", (c["product_id"],)
        ).fetchone()
        if ins:
            c["complaints"] = json.loads(ins["complaints_json"] or "[]")
    payload = {
        "opportunity": {
            k: opp[k]
            for k in (
                "title",
                "description",
                "target_user",
                "core_pain",
                "proposed_solution",
                "wedge",
                "monetization",
                "distribution",
                "build_type",
                "build_difficulty",
                "competitor_weakness",
                "risks_json",
                "why_now",
            )
        },
        "cluster": {
            "label": opp["cluster_label"],
            "summary": opp["cluster_summary"],
            "persona": opp["persona"],
            "category": opp["category"],
        },
        "pain_signals": pains,
        "competitors": competitors,
        "common_complaints": json.loads(comp["common_complaints_json"]) if comp else [],
        "pricing_distribution": json.loads(comp["pricing_distribution_json"]) if comp else {},
        "evidence_external_ids": [p["external_id"] for p in pains]
        + [c.get("external_id") for c in competitors if c.get("external_id")],
    }
    data, model = provider.chat_json(
        "ANALYSIS_MODEL",
        BRIEF_SYSTEM,
        json.dumps(payload, ensure_ascii=False),
        task="builder_brief",
        conn=conn,
        timeout=180,
    )
    if not isinstance(data, dict) or data.get("error"):
        raise ValidationFailed(
            "the model did not return a usable brief",
            details={"error": data.get("error") if isinstance(data, dict) else str(data)[:200]},
        )
    try:
        brief = Brief.coerce(data)
    except ValidationError as exc:
        raise ValidationFailed(
            "brief failed schema validation", details={"errors": json.loads(exc.json())[:5]}
        ) from exc
    known = {c["name"].lower() for c in competitors}
    brief.competitors = [
        c for c in brief.competitors if str(c.get("name", "")).lower() in known
    ]  # never invent competitors
    brief_id = new_id()
    conn.execute(
        "INSERT INTO builder_briefs(id,opportunity_id,content_json,generated_by) VALUES(?,?,?,?)",
        (brief_id, opportunity_id, brief.model_dump_json(), "fixture" if model == "fixture" else model),
    )
    conn.commit()
    saved = get_brief(conn, opportunity_id)
    if saved is None:  # pragma: no cover - inserted just above
        raise RuntimeError("builder brief was not persisted")
    return saved
