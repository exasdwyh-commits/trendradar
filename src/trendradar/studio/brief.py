"""The one-page daily brief (简报速览): stories worth writing, rising pain signals, opportunities.

Items are frozen per day (so what you saw stays what you saw) and carry the user's triage status.
`refresh` adds newly assessed material to today's page without touching existing statuses.
"""

from __future__ import annotations

import json
import sqlite3

from ..core.errors import NotConfigured, NotFound, SourceError, ValidationFailed
from ..core.ids import new_id
from ..core.timeutil import day_key, days_ago, iso
from ..db.connection import rows_to_dicts
from ..providers.llm import get_llm
from .documents import create_document, seed_markdown
from .materials import get_material, material_from_cluster, material_from_opportunity, material_from_signal
from .stories import ASSESS_SYSTEM, LANE_NAMES, LANES, _store

STORY_LIMIT = 12
STORY_MIN_VALUE = 55
STORY_MAX_PER_SOURCE = 3
SIGNAL_LIMIT = 5
OPPORTUNITY_LIMIT = 5


def reassess_item(conn: sqlite3.Connection, item_id: str) -> dict:
    """Reassess one story while preserving triage and manuscript links."""
    item = conn.execute("SELECT * FROM brief_items WHERE id=?", (item_id,)).fetchone()
    if not item:
        raise NotFound("简报条目不存在")
    if item["section"] != "story" or item["ref_type"] != "signal":
        raise ValidationFailed("只有文章选题支持重新评估")
    signal = conn.execute("SELECT * FROM signals WHERE id=?", (item["ref_id"],)).fetchone()
    if not signal:
        raise NotFound("原始资料不存在")
    provider = get_llm()
    if not provider.slot_enabled("FAST_MODEL"):
        raise NotConfigured("请先配置采集与标题模型 FAST_MODEL，再重新评估")
    payload = {
        "items": [
            {
                "id": signal["id"],
                "external_id": signal["external_id"],
                "title": signal["title"],
                "text": (signal["content"] or "")[:6000],
                "source": item["source_name"],
                "published_at": signal["created_at"],
            }
        ]
    }
    try:
        output, model = provider.chat_json(
            "FAST_MODEL",
            ASSESS_SYSTEM,
            json.dumps(payload, ensure_ascii=False),
            task="assess_stories",
            conn=conn,
        )
    except RuntimeError as exc:
        raise SourceError("重新评估失败，原评分已保留，请稍后重试") from exc
    results = output.get("items") if isinstance(output, dict) else None
    result = (
        next((r for r in results if isinstance(r, dict) and r.get("id") == signal["id"]), None)
        if isinstance(results, list)
        else None
    )
    if (
        not result
        or result.get("lane") not in LANES
        or not isinstance(result.get("business_value"), (int, float))
        or not isinstance(result.get("why"), str)
        or not isinstance(result.get("angles"), list)
    ):
        raise ValidationFailed("评估结果无效，原评分已保留")
    method = "fixture" if model == "fixture" else "model"
    _store(conn, signal["id"], result, method=method, model=model)
    for row in conn.execute(
        "SELECT id,meta_json FROM brief_items WHERE ref_type='signal' AND ref_id=?", (signal["id"],)
    ).fetchall():
        meta = {**json.loads(row["meta_json"] or "{}"), "method": method, "model": model}
        conn.execute(
            "UPDATE brief_items SET lane=?,score=?,why=?,angles_json=?,meta_json=? WHERE id=?",
            (
                result["lane"],
                max(0, min(100, result["business_value"])),
                result["why"][:300],
                json.dumps([str(a)[:80] for a in result["angles"][:3]], ensure_ascii=False),
                json.dumps(meta, ensure_ascii=False),
                row["id"],
            ),
        )
    conn.commit()
    return {"model": model, "method": method, "input_characters": len(payload["items"][0]["text"])}


def _upsert(conn: sqlite3.Connection, day: str, item: dict) -> None:
    conn.execute(
        """
        INSERT INTO brief_items(id,day,section,ref_type,ref_id,rank,title,url,source_name,lane,summary,why,angles_json,score,origin,meta_json)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(day,ref_type,ref_id) DO UPDATE SET rank=excluded.rank,title=excluded.title,summary=excluded.summary,
          why=excluded.why,angles_json=excluded.angles_json,score=excluded.score,meta_json=excluded.meta_json
        """,
        (
            new_id(),
            day,
            item["section"],
            item["ref_type"],
            item["ref_id"],
            item["rank"],
            item["title"][:300],
            item.get("url"),
            item.get("source_name"),
            item.get("lane"),
            (item.get("summary") or "")[:600],
            (item.get("why") or "")[:300],
            json.dumps(item.get("angles") or [], ensure_ascii=False),
            float(item.get("score") or 0),
            item.get("origin") or "live",
            json.dumps(item.get("meta") or {}, ensure_ascii=False),
        ),
    )


def _drop_mock_when_live(rows: list) -> list:
    """Demo fixtures are never mixed with real data: once live items exist, the mock ones step aside."""
    origin = lambda r: r["origin"] if not isinstance(r, dict) else r.get("origin")  # noqa: E731
    if any(origin(r) == "live" for r in rows):
        return [r for r in rows if origin(r) != "mock"]
    return rows


def _story_candidates(conn: sqlite3.Connection, *, since_days: int = 4) -> list[dict]:
    rows = conn.execute(
        """
        SELECT s.id, s.title, s.url, s.content, s.created_at, s.fetched_at, s.origin, s.metadata_json,
               so.name AS source_name, a.lane, a.business_value, a.why, a.angles_json, a.method
        FROM story_assessments a
        JOIN signals s ON s.id = a.signal_id
        JOIN sources so ON so.id = s.source_id
        WHERE s.dedup_of IS NULL AND COALESCE(s.created_at, s.fetched_at) >= ?
          AND NOT EXISTS (SELECT 1 FROM brief_items b WHERE b.ref_type='signal' AND b.ref_id=s.id AND b.status='dismissed')
        ORDER BY a.business_value DESC, COALESCE(s.created_at, s.fetched_at) DESC
        LIMIT 200
        """,
        (iso(days_ago(since_days)),),
    ).fetchall()
    rows = _drop_mock_when_live(rows)
    picked: list[dict] = []
    per_source: dict[str, int] = {}
    distinct_sources = len({r["source_name"] for r in rows})
    cap = (
        STORY_MAX_PER_SOURCE if distinct_sources >= 3 else STORY_LIMIT
    )  # diversity only matters with many feeds
    for r in rows:
        if r["business_value"] < STORY_MIN_VALUE and r["method"] != "rule":
            continue
        if r["method"] == "rule" and r["business_value"] < 45:
            continue
        if per_source.get(r["source_name"], 0) >= cap:
            continue
        per_source[r["source_name"]] = per_source.get(r["source_name"], 0) + 1
        meta = json.loads(r["metadata_json"] or "{}")
        summary = meta.get("summary") or " ".join((r["content"] or "").split())[:240]
        picked.append(
            {
                "section": "story",
                "ref_type": "signal",
                "ref_id": r["id"],
                "title": r["title"],
                "url": r["url"],
                "source_name": r["source_name"],
                "lane": r["lane"],
                "summary": summary,
                "why": r["why"],
                "angles": json.loads(r["angles_json"] or "[]"),
                "score": r["business_value"],
                "origin": r["origin"],
                "meta": {"method": r["method"], "published_at": r["created_at"]},
            }
        )
        if len(picked) >= STORY_LIMIT:
            break
    return picked


def _signal_candidates(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT c.*, o.id AS opportunity_id, o.title AS opportunity_title
        FROM pain_clusters c LEFT JOIN opportunities o ON o.pain_cluster_id=c.id
        WHERE c.session_id IS NULL AND c.signal_count >= 3
        ORDER BY CASE c.stage WHEN 'emerging' THEN 0 WHEN 'growing' THEN 1 WHEN 'new' THEN 2 WHEN 'stable' THEN 3 ELSE 4 END,
                 c.velocity DESC, c.signal_count DESC
        LIMIT ?
        """,
        (SIGNAL_LIMIT,),
    ).fetchall()
    stage_zh = {"emerging": "爆发中", "growing": "上升", "stable": "平稳", "fading": "减弱", "new": "新出现"}
    out = []
    for r in rows:
        why = (
            f"{stage_zh.get(r['stage'], r['stage'])} · 近 7 天速度 ×{r['velocity']:.1f} · "
            f"{r['signal_count']} 条真实抱怨 / {r['unique_users']} 人 / {r['source_count']} 个来源"
        )
        angles = [
            f"为什么 {r['persona'] or '用户'} 现在集中抱怨这个问题",
            "现有工具为什么没解决",
            "谁会为解决它付费",
        ]
        out.append(
            {
                "section": "signal",
                "ref_type": "pain_cluster",
                "ref_id": r["id"],
                "title": r["label"],
                "source_name": f"{r['source_count']} 个来源",
                "lane": None,
                "summary": r["summary"] or "",
                "why": why,
                "angles": angles,
                "score": min(100.0, 40 + r["velocity"] * 10 + r["signal_count"]),
                "origin": r["data_mode"],
                "meta": {
                    "stage": r["stage"],
                    "velocity": r["velocity"],
                    "persona": r["persona"],
                    "opportunity_id": r["opportunity_id"],
                },
            }
        )
    return out


def _opportunity_candidates(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT * FROM opportunities WHERE session_id IS NULL AND status NOT IN ('rejected','archived')
        ORDER BY opportunity_score DESC LIMIT ?
        """,
        (OPPORTUNITY_LIMIT,),
    ).fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "section": "opportunity",
                "ref_type": "opportunity",
                "ref_id": r["id"],
                "title": r["title"],
                "source_name": "机会雷达",
                "lane": "BUSINESS_MODEL",
                "summary": "\n\n".join(
                    x
                    for x in [
                        r["description"],
                        f"切口：{r['wedge']}" if r["wedge"] else "",
                        f"对手弱点：{r['competitor_weakness']}" if r["competitor_weakness"] else "",
                    ]
                    if x
                ),
                "why": r["why_now"] or r["core_pain"] or "",
                "angles": ["这个机会为什么现在成立", "现有产品的空当在哪里", "一人公司怎么切入"],
                "score": r["opportunity_score"],
                "origin": r["data_mode"],
                "meta": {
                    "confidence": r["confidence"],
                    "status": r["status"],
                    "target_user": r["target_user"],
                },
            }
        )
    return out


def build_brief(conn: sqlite3.Connection, day: str | None = None) -> dict:
    """(Re)build one day's brief. Idempotent: existing rows keep their id/status; untouched rows that the
    reader never acted on are pruned so a rebuild after a live fetch does not leave stale items behind."""
    day = day or day_key()
    counts = {"story": 0, "signal": 0, "opportunity": 0}
    keep: list[tuple[str, str]] = []
    for section_items in (
        _drop_mock_when_live(_story_candidates(conn)),
        _drop_mock_when_live(_signal_candidates(conn)),
        _drop_mock_when_live(_opportunity_candidates(conn)),
    ):
        for rank, item in enumerate(section_items, start=1):
            item["rank"] = rank
            _upsert(conn, day, item)
            counts[item["section"]] += 1
            keep.append((item["ref_type"], item["ref_id"]))
    stale = conn.execute(
        "SELECT id, ref_type, ref_id FROM brief_items WHERE day=? AND status='new'", (day,)
    ).fetchall()
    for row in stale:
        if (row["ref_type"], row["ref_id"]) not in keep:
            conn.execute("DELETE FROM brief_items WHERE id=?", (row["id"],))
    conn.commit()
    return {"day": day, **counts}


def _row(item: dict) -> dict:
    item["angles"] = json.loads(item.pop("angles_json") or "[]")
    item["meta"] = json.loads(item.pop("meta_json") or "{}")
    item["lane_name"] = LANE_NAMES.get(item.get("lane") or "", item.get("lane"))
    return item


def get_brief(conn: sqlite3.Connection, day: str | None = None, *, include_dismissed: bool = False) -> dict:
    day = day or day_key()
    if not conn.execute("SELECT 1 FROM brief_items WHERE day=? LIMIT 1", (day,)).fetchone():
        latest = conn.execute("SELECT day FROM brief_items ORDER BY day DESC LIMIT 1").fetchone()
        if latest and day == day_key():
            day = latest["day"]
    where = "day=?" + ("" if include_dismissed else " AND status!='dismissed'")
    items = [
        _row(i)
        for i in rows_to_dicts(
            conn.execute(f"SELECT * FROM brief_items WHERE {where} ORDER BY section, rank", (day,)).fetchall()
        )
    ]
    sections: dict[str, list[dict]] = {"story": [], "signal": [], "opportunity": []}
    for i in items:
        sections[i["section"]].append(i)
    recent_materials = rows_to_dicts(
        conn.execute(
            "SELECT id,kind,title,url,source_name,origin,created_at FROM materials WHERE archived=0 ORDER BY created_at DESC LIMIT 8"
        ).fetchall()
    )
    llm = get_llm()
    last_job = conn.execute(
        "SELECT started_at, status, job_type FROM jobs WHERE job_type IN ('daily','brief','seed') ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    days = [
        r[0]
        for r in conn.execute("SELECT DISTINCT day FROM brief_items ORDER BY day DESC LIMIT 14").fetchall()
    ]
    origins = {i["origin"] for i in items}
    return {
        "day": day,
        "today": day_key(),
        "days": days,
        "sections": sections,
        "counts": {k: len(v) for k, v in sections.items()},
        "recent_materials": recent_materials,
        "data_mode": "mixed" if len(origins) > 1 else (next(iter(origins)) if origins else "live"),
        "models": {"fast": llm.slot_enabled("FAST_MODEL"), "analysis": llm.slot_enabled("ANALYSIS_MODEL")},
        "last_job": dict(last_job) if last_job else None,
    }


def set_item_status(conn: sqlite3.Connection, item_id: str, status: str) -> dict:
    if status not in ("new", "saved", "dismissed"):
        raise ValidationFailed("未知状态", details={"allowed": ["new", "saved", "dismissed"]})
    item = conn.execute("SELECT * FROM brief_items WHERE id=?", (item_id,)).fetchone()
    if not item:
        raise NotFound("简报条目不存在", details={"id": item_id})
    material_id = item["material_id"]
    if status == "saved" and not material_id:
        material_id = _material_for(conn, item)
    conn.execute(
        "UPDATE brief_items SET status=?, material_id=COALESCE(?, material_id) WHERE id=?",
        (status, material_id, item_id),
    )
    conn.commit()
    return _row(dict(conn.execute("SELECT * FROM brief_items WHERE id=?", (item_id,)).fetchone()))


def _material_for(conn: sqlite3.Connection, item: sqlite3.Row) -> str:
    if item["ref_type"] == "signal":
        return material_from_signal(conn, item["ref_id"])
    if item["ref_type"] == "pain_cluster":
        return material_from_cluster(conn, item["ref_id"])
    return material_from_opportunity(conn, item["ref_id"])


def extend_item(conn: sqlite3.Connection, item_id: str, *, angle: str | None = None) -> dict:
    """「延伸创作」: material + a new document seeded from the item. Returns ids."""
    item = conn.execute("SELECT * FROM brief_items WHERE id=?", (item_id,)).fetchone()
    if not item:
        raise NotFound("简报条目不存在", details={"id": item_id})
    material_id = item["material_id"] or _material_for(conn, item)
    material = get_material(conn, material_id)
    angles = json.loads(item["angles_json"] or "[]")
    title = angle or (angles[0] if angles else item["title"])
    document_id = create_document(
        conn,
        title=title,
        content_md=seed_markdown(material, why=item["why"], angles=angles),
        thesis=item["why"] or "",
        lane=item["lane"],
        seed_material_id=material_id,
        meta={"brief_item_id": item_id, "brief_day": item["day"], "angle": angle},
    )
    conn.execute(
        "UPDATE brief_items SET status='used', material_id=?, document_id=? WHERE id=?",
        (material_id, document_id, item_id),
    )
    conn.commit()
    return {"document_id": document_id, "material_id": material_id, "item_id": item_id}
