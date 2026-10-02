"""Read models for the API: opportunity cards/details, cluster details, radar rows."""

from __future__ import annotations

import json
import sqlite3

from ..core.timeutil import day_key
from ..trends.velocity import series

CARD_COLUMNS = """o.id, o.pain_cluster_id, o.title, o.description, o.target_user, o.core_pain, o.proposed_solution, o.wedge, o.monetization, o.distribution,
 o.build_type, o.build_difficulty, o.why_now, o.competitor_weakness, o.risks_json, o.next_action, o.status, o.opportunity_score, o.confidence, o.data_mode,
 o.version, o.first_seen, o.last_seen, o.signal_count, o.growth, o.generated_by, o.session_id, o.created_at, o.updated_at,
 pc.label AS cluster_label, pc.persona, pc.category, pc.stage, pc.velocity, pc.acceleration, pc.unique_users, pc.source_count"""


def _card(conn: sqlite3.Connection, row: sqlite3.Row, *, with_scores: bool = True) -> dict:
    d = dict(row)
    d["risks"] = json.loads(d.pop("risks_json") or "[]")
    if with_scores:
        d["scores"] = {
            r["dimension"]: {
                "score": r["score"],
                "reason": r["reason"],
                "confidence": r["confidence"],
                "method": r["method"],
                "evidence_ids": json.loads(r["evidence_ids_json"] or "[]"),
            }
            for r in conn.execute("SELECT * FROM opportunity_scores WHERE opportunity_id=?", (d["id"],))
        }
    comp = conn.execute(
        "SELECT competitor_count, density, maturity FROM competition_profiles WHERE pain_cluster_id=?",
        (d["pain_cluster_id"],),
    ).fetchone()
    d["competition"] = dict(comp) if comp else None
    return d


def list_opportunities(
    conn: sqlite3.Connection,
    *,
    status: list[str] | None = None,
    persona: str | None = None,
    category: str | None = None,
    min_score: float | None = None,
    q: str | None = None,
    sort: str = "opportunity_score",
    limit: int = 50,
    offset: int = 0,
    include_sessions: bool = False,
    data_mode: str | None = None,
) -> tuple[list[dict], int]:
    where = [] if include_sessions else ["o.session_id IS NULL"]
    params: list = []
    if status:
        where.append(f"o.status IN ({','.join('?' * len(status))})")
        params.extend(status)
    else:
        where.append("o.status NOT IN ('archived')")
    if persona:
        where.append("pc.persona=?")
        params.append(persona)
    if category:
        where.append("pc.category=?")
        params.append(category)
    if data_mode:
        where.append("o.data_mode=?")
        params.append(data_mode)
    if min_score is not None:
        where.append("o.opportunity_score>=?")
        params.append(min_score)
    if q:
        where.append("(o.title LIKE ? OR o.core_pain LIKE ? OR o.description LIKE ? OR pc.label LIKE ?)")
        params.extend([f"%{q}%"] * 4)
    sort_sql = {
        "opportunity_score": "o.opportunity_score DESC",
        "growth": "o.growth DESC",
        "last_seen": "o.last_seen DESC",
        "first_seen": "o.first_seen DESC",
        "confidence": "o.confidence DESC",
        "signal_count": "o.signal_count DESC",
    }.get(sort, "o.opportunity_score DESC")
    clause = " AND ".join(where) or "1=1"
    total = conn.execute(
        f"SELECT COUNT(*) FROM opportunities o JOIN pain_clusters pc ON pc.id=o.pain_cluster_id WHERE {clause}",
        params,
    ).fetchone()[0]
    rows = conn.execute(
        f"SELECT {CARD_COLUMNS} FROM opportunities o JOIN pain_clusters pc ON pc.id=o.pain_cluster_id WHERE {clause} ORDER BY {sort_sql}, o.confidence DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    return [_card(conn, r) for r in rows], int(total)


def get_opportunity(conn: sqlite3.Connection, opportunity_id: str) -> dict | None:
    row = conn.execute(
        f"SELECT {CARD_COLUMNS} FROM opportunities o JOIN pain_clusters pc ON pc.id=o.pain_cluster_id WHERE o.id=?",
        (opportunity_id,),
    ).fetchone()
    if row is None:
        return None
    d = _card(conn, row)
    d["evidence"] = [
        dict(r)
        for r in conn.execute(
            "SELECT id, kind, signal_id, product_id, source_id, quote, url, occurred_at, origin FROM evidence WHERE subject_type='opportunity' AND subject_id=? ORDER BY CASE kind WHEN 'pain' THEN 0 WHEN 'complaint' THEN 1 ELSE 2 END, occurred_at DESC",
            (opportunity_id,),
        )
    ]
    d["pain_signals"] = [
        {**dict(r), "friction": json.loads(r["friction_json"] or "[]")}
        for r in conn.execute(
            """SELECT ps.id, ps.signal_id, ps.problem, ps.context, ps.severity, ps.frequency, ps.willingness_to_pay, ps.existing_workaround, ps.current_solution, ps.friction_json, ps.evidence_quote, ps.confidence, ps.generated_by,
                      s.title, s.url, s.source_id, s.origin, s.author, s.created_at, s.engagement_json
               FROM pain_signals ps JOIN signals s ON s.id=ps.signal_id WHERE ps.cluster_id=? ORDER BY ps.severity DESC""",
            (d["pain_cluster_id"],),
        )
    ]
    for ps in d["pain_signals"]:
        ps["engagement"] = json.loads(ps.pop("engagement_json") or "{}")
        ps.pop("friction_json", None)
    comp = conn.execute(
        "SELECT * FROM competition_profiles WHERE pain_cluster_id=?", (d["pain_cluster_id"],)
    ).fetchone()
    if comp:
        profile = dict(comp)
        for key in ("common_features", "common_complaints", "competitors"):
            profile[key] = json.loads(profile.pop(f"{key}_json") or "[]")
        profile["pricing_distribution"] = json.loads(profile.pop("pricing_distribution_json") or "{}")
        for c in profile["competitors"]:
            p = conn.execute(
                "SELECT url, website, tagline, launched_at, review_count, pricing_origin FROM products WHERE id=?",
                (c["product_id"],),
            ).fetchone()
            ins = conn.execute(
                "SELECT pros_json, cons_json, complaints_json, review_summary, derived_from, sample_size FROM product_insights WHERE product_id=?",
                (c["product_id"],),
            ).fetchone()
            if p:
                c.update(dict(p))
            c["insights"] = (
                {
                    "pros": json.loads(ins["pros_json"]),
                    "cons": json.loads(ins["cons_json"]),
                    "complaints": json.loads(ins["complaints_json"]),
                    "summary": ins["review_summary"],
                    "derived_from": ins["derived_from"],
                    "sample_size": ins["sample_size"],
                }
                if ins
                else None
            )
        d["competition"] = profile
    d["status_log"] = [
        dict(r)
        for r in conn.execute(
            "SELECT from_status, to_status, note, created_at FROM opportunity_status_log WHERE opportunity_id=? ORDER BY created_at",
            (opportunity_id,),
        )
    ]
    d["trend_series"] = series(conn, "pain_cluster", d["pain_cluster_id"], 30)
    brief = conn.execute(
        "SELECT id, generated_by, created_at FROM builder_briefs WHERE opportunity_id=? ORDER BY created_at DESC LIMIT 1",
        (opportunity_id,),
    ).fetchone()
    d["brief"] = dict(brief) if brief else None
    return d


def today_payload(
    conn: sqlite3.Connection, *, min_score: float, min_confidence: float, day: str | None = None
) -> dict:
    day = day or day_key()
    picks_rows = conn.execute(
        "SELECT opportunity_id, rank, reason FROM today_picks WHERE day=? ORDER BY rank", (day,)
    ).fetchall()
    if not picks_rows:
        latest = conn.execute("SELECT day FROM today_picks ORDER BY day DESC LIMIT 1").fetchone()
        if latest:
            day = latest["day"]
            picks_rows = conn.execute(
                "SELECT opportunity_id, rank, reason FROM today_picks WHERE day=? ORDER BY rank", (day,)
            ).fetchall()
    picks = []
    for p in picks_rows:
        card = get_card(conn, p["opportunity_id"])
        if card:
            card["pick_reason"] = p["reason"]
            picks.append(card)
    picked_ids = {p["id"] for p in picks}
    radar, _ = list_opportunities(conn, limit=8, sort="opportunity_score")
    also = [c for c in radar if c["id"] not in picked_ids][:4]
    brief = conn.execute(
        "SELECT content_md, created_at FROM reports WHERE kind='daily_brief' ORDER BY day DESC LIMIT 1"
    ).fetchone()
    last_job = conn.execute(
        "SELECT id, job_type, status, started_at, finished_at FROM jobs WHERE job_type IN ('daily','seed') ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    counts = conn.execute(
        "SELECT COUNT(*) n, SUM(origin='live') live, SUM(origin='mock') mock FROM signals WHERE dedup_of IS NULL"
    ).fetchone()
    return {
        "day": day,
        "picks": picks,
        "also_on_radar": also,
        "thresholds": {"min_score": min_score, "min_confidence": min_confidence},
        "brief_md": brief["content_md"] if brief else None,
        "brief_at": brief["created_at"] if brief else None,
        "last_job": dict(last_job) if last_job else None,
        "data": {
            "signals": int(counts["n"] or 0),
            "live": int(counts["live"] or 0),
            "mock": int(counts["mock"] or 0),
        },
    }


def get_card(conn: sqlite3.Connection, opportunity_id: str) -> dict | None:
    row = conn.execute(
        f"SELECT {CARD_COLUMNS} FROM opportunities o JOIN pain_clusters pc ON pc.id=o.pain_cluster_id WHERE o.id=?",
        (opportunity_id,),
    ).fetchone()
    return _card(conn, row) if row else None


def radar_payload(conn: sqlite3.Connection, window_days: int) -> dict:
    rows = conn.execute(
        """SELECT pc.id, pc.label, pc.summary, pc.persona, pc.category, pc.stage, pc.velocity, pc.acceleration, pc.signal_count, pc.unique_users, pc.source_count,
                  pc.first_seen, pc.last_seen, pc.data_mode, pc.analysis_status, o.id AS opportunity_id, o.opportunity_score, o.status AS opportunity_status
           FROM pain_clusters pc LEFT JOIN opportunities o ON o.pain_cluster_id=pc.id
           WHERE pc.session_id IS NULL AND pc.signal_count>=1 ORDER BY pc.velocity DESC, pc.signal_count DESC LIMIT 200"""
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        s = series(conn, "pain_cluster", r["id"], window_days)
        d["series"] = s
        d["window_signals"] = sum(s)
        if d["window_signals"] == 0 and window_days < 90:
            continue
        out.append(d)
    stage_counts: dict[str, int] = {}
    for d in out:
        stage_counts[d["stage"]] = stage_counts.get(d["stage"], 0) + 1
    return {"window_days": window_days, "clusters": out, "stages": stage_counts}


def cluster_detail(conn: sqlite3.Connection, cluster_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM pain_clusters WHERE id=?", (cluster_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d.pop("centroid", None)
    d["signals"] = [
        {
            **dict(r),
            "engagement": json.loads(r["engagement_json"] or "{}"),
            "excerpt": (r["content"] or "")[:400],
        }
        for r in conn.execute(
            """SELECT s.id, s.external_id, s.source_id, s.origin, s.url, s.title, s.content, s.author, s.created_at, s.engagement_json, s.rule_score, pci.similarity, c.persona, c.category, c.relevance
               FROM pain_cluster_items pci JOIN signals s ON s.id=pci.signal_id LEFT JOIN signal_classifications c ON c.signal_id=s.id
               WHERE pci.cluster_id=? ORDER BY pci.similarity DESC LIMIT 100""",
            (cluster_id,),
        )
    ]
    for s in d["signals"]:
        s.pop("engagement_json", None)
        s.pop("content", None)
    opp = conn.execute(
        "SELECT id, title, opportunity_score, status FROM opportunities WHERE pain_cluster_id=?",
        (cluster_id,),
    ).fetchone()
    d["opportunity"] = dict(opp) if opp else None
    d["series"] = series(conn, "pain_cluster", cluster_id, 30)
    return d


def signal_detail(conn: sqlite3.Connection, signal_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM signals WHERE id=?", (signal_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["engagement"] = json.loads(d.pop("engagement_json") or "{}")
    d["metadata"] = json.loads(d.pop("metadata_json") or "{}")
    d.pop("raw_json", None)
    cls = conn.execute("SELECT * FROM signal_classifications WHERE signal_id=?", (signal_id,)).fetchone()
    d["classification"] = dict(cls) if cls else None
    ps = conn.execute("SELECT * FROM pain_signals WHERE signal_id=?", (signal_id,)).fetchone()
    d["pain_signal"] = {**dict(ps), "friction": json.loads(ps["friction_json"] or "[]")} if ps else None
    d["clusters"] = [
        dict(r)
        for r in conn.execute(
            "SELECT pc.id, pc.label, pc.session_id FROM pain_cluster_items pci JOIN pain_clusters pc ON pc.id=pci.cluster_id WHERE pci.signal_id=?",
            (signal_id,),
        )
    ]
    return d


def product_detail(conn: sqlite3.Connection, product_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["categories"] = json.loads(d.pop("categories_json") or "[]")
    d["makers"] = json.loads(d.pop("makers_json") or "[]")
    d["credibility"] = json.loads(d.pop("credibility_json") or "{}")
    raw = json.loads(d.pop("raw_json") or "{}")
    d["comment_samples"] = raw.get("comment_samples", [])
    ins = conn.execute("SELECT * FROM product_insights WHERE product_id=?", (product_id,)).fetchone()
    d["insights"] = (
        {
            **dict(ins),
            "pros": json.loads(ins["pros_json"]),
            "cons": json.loads(ins["cons_json"]),
            "complaints": json.loads(ins["complaints_json"]),
        }
        if ins
        else None
    )
    if d["insights"]:
        for k in ("pros_json", "cons_json", "complaints_json"):
            d["insights"].pop(k, None)
    d["clusters"] = [
        dict(r)
        for r in conn.execute(
            "SELECT pc.id, pc.label, pc.product_count, pc.maturity FROM product_cluster_items i JOIN product_clusters pc ON pc.id=i.cluster_id WHERE i.product_id=?",
            (product_id,),
        )
    ]
    d["solves"] = [
        dict(r)
        for r in conn.execute(
            "SELECT pc.id, pc.label, e.weight FROM edges e JOIN pain_clusters pc ON pc.id=e.from_id WHERE e.relation='solved_by' AND e.to_id=? ORDER BY e.weight DESC",
            (product_id,),
        )
    ]
    return d
