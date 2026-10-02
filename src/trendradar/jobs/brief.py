"""Daily Brief: a short markdown report built from the day's pipeline stats and Today picks."""

from __future__ import annotations

import json
import sqlite3

from ..core.ids import stable_id
from ..core.timeutil import iso, utcnow


def write_daily_brief(conn: sqlite3.Connection, day: str, stats: dict) -> str:
    picks = conn.execute(
        """SELECT t.rank, t.reason, o.id, o.title, o.opportunity_score, o.confidence, o.core_pain, o.data_mode, pc.stage, pc.velocity
           FROM today_picks t JOIN opportunities o ON o.id=t.opportunity_id JOIN pain_clusters pc ON pc.id=o.pain_cluster_id
           WHERE t.day=? ORDER BY t.rank""",
        (day,),
    ).fetchall()
    emerging = conn.execute(
        "SELECT label, velocity, signal_count, source_count FROM pain_clusters WHERE session_id IS NULL AND stage='emerging' ORDER BY velocity DESC LIMIT 5"
    ).fetchall()
    new_clusters = conn.execute(
        "SELECT label, signal_count FROM pain_clusters WHERE session_id IS NULL AND substr(created_at,1,10)=? ORDER BY signal_count DESC LIMIT 5",
        (day,),
    ).fetchall()
    collect = stats.get("collect") or {}
    signals = (collect.get("signals") or {}) if isinstance(collect, dict) else {}
    lines = [f"# Daily Brief — {day}", ""]
    lines.append(
        f"Collected {signals.get('inserted', 0)} new signals ({signals.get('duplicates', 0)} duplicates dropped) from {collect.get('sources_ok', 0)} source(s); "
        f"{(stats.get('classify') or {}).get('pain', 0)} classified as pain; {(stats.get('cluster') or {}).get('created', 0)} new cluster(s)."
    )
    lines.append("")
    lines.append(
        "## Today's opportunities"
        if picks
        else "## Today's opportunities\n\nNo opportunity met today's quality bar (score ≥ 70, confidence ≥ 60). Better nothing than noise."
    )
    for p in picks:
        badge = "" if p["data_mode"] == "live" else f" _[{p['data_mode']}]_"
        lines.append(
            f"{p['rank']}. **{p['title']}**{badge} — score {p['opportunity_score']:.0f}, confidence {p['confidence']:.0f}, trend {p['stage']} (×{p['velocity'] or 0:.1f})  "
        )
        if p["core_pain"]:
            lines.append(f"   {p['core_pain']}")
    if emerging:
        lines += ["", "## Emerging pain clusters"] + [
            f"- {e['label']} — velocity ×{e['velocity']:.1f}, {e['signal_count']} signals / {e['source_count']} sources"
            for e in emerging
        ]
    if new_clusters:
        lines += ["", "## New clusters today"] + [
            f"- {c['label']} ({c['signal_count']} signals)" for c in new_clusters
        ]
    analyze = stats.get("analyze") or {}
    if isinstance(analyze, dict) and analyze.get("skipped"):
        lines += [
            "",
            f"> {analyze.get('skipped')} cluster(s) passed the gate but were not analysed: {analyze.get('reason')}",
        ]
    content = "\n".join(lines) + "\n"
    report_id = stable_id("report", day, "daily_brief")
    conn.execute(
        "INSERT INTO reports(id,day,kind,content_md,data_json,created_at) VALUES(?,?,?,?,?,?) ON CONFLICT(day,kind) DO UPDATE SET content_md=excluded.content_md, data_json=excluded.data_json, created_at=excluded.created_at",
        (
            report_id,
            day,
            "daily_brief",
            content,
            json.dumps({"picks": [dict(p) for p in picks], "stats": stats}, ensure_ascii=False, default=str),
            iso(utcnow()),
        ),
    )
    conn.commit()
    return report_id
