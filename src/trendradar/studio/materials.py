"""Material library: the things a piece is built from (stories, pain signals, clusters, opportunities, URLs, notes)."""

from __future__ import annotations

import json
import sqlite3
from typing import overload

from ..core.errors import NotFound, ValidationFailed
from ..core.ids import new_id
from ..core.timeutil import iso
from ..db.connection import row_to_dict, rows_to_dicts
from ..sources.article import extract_article
from ..sources.safe_fetch import fetch_public_page

_ALLOWED_KINDS = {"story", "signal", "cluster", "opportunity", "url", "note"}


@overload
def _parse(row: dict) -> dict: ...
@overload
def _parse(row: None) -> None: ...
@overload
def _parse(row: dict | None) -> dict | None: ...
def _parse(row: dict | None) -> dict | None:
    if row is None:
        return None
    row["tags"] = json.loads(row.pop("tags_json") or "[]")
    return row


def get_material(conn: sqlite3.Connection, material_id: str) -> dict:
    row = _parse(row_to_dict(conn.execute("SELECT * FROM materials WHERE id=?", (material_id,)).fetchone()))
    if not row:
        raise NotFound("素材不存在", details={"id": material_id})
    row["documents"] = rows_to_dicts(
        conn.execute(
            "SELECT d.id, d.title, d.status FROM document_materials dm JOIN documents d ON d.id=dm.document_id "
            "WHERE dm.material_id=? ORDER BY d.updated_at DESC",
            (material_id,),
        ).fetchall()
    )
    return row


def list_materials(
    conn: sqlite3.Connection,
    *,
    q: str | None = None,
    kind: str | None = None,
    include_archived: bool = False,
    limit: int = 200,
) -> list[dict]:
    where = ["1=1"] if include_archived else ["archived=0"]
    params: list = []
    if kind:
        where.append("kind=?")
        params.append(kind)
    if q:
        where.append(
            "(title LIKE ? OR summary LIKE ? OR quote LIKE ? OR source_name LIKE ? OR content LIKE ?)"
        )
        params.extend([f"%{q}%"] * 5)
    rows = conn.execute(
        f"SELECT m.*, (SELECT COUNT(*) FROM document_materials dm WHERE dm.material_id=m.id) AS document_count "
        f"FROM materials m WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT ?",
        (*params, limit),
    ).fetchall()
    return [_parse(r) for r in rows_to_dicts(rows)]


def create_material(
    conn: sqlite3.Connection,
    *,
    kind: str,
    title: str,
    url: str | None = None,
    source_name: str | None = None,
    author: str | None = None,
    published_at: str | None = None,
    summary: str = "",
    quote: str = "",
    content: str = "",
    ref_type: str | None = None,
    ref_id: str | None = None,
    lane: str | None = None,
    tags: list[str] | None = None,
    origin: str = "manual",
) -> str:
    if kind not in _ALLOWED_KINDS:
        raise ValidationFailed("未知素材类型", details={"kind": kind})
    title = (title or "").strip()
    if not title:
        raise ValidationFailed("素材需要标题")
    if ref_type and ref_id:
        existing = conn.execute(
            "SELECT id FROM materials WHERE ref_type=? AND ref_id=? AND archived=0", (ref_type, ref_id)
        ).fetchone()
        if existing:
            return existing["id"]
    material_id = new_id()
    conn.execute(
        """
        INSERT INTO materials(id,kind,title,url,source_name,author,published_at,summary,quote,content,ref_type,ref_id,
                              lane,tags_json,origin)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            material_id,
            kind,
            title[:300],
            url,
            source_name,
            author,
            published_at,
            (summary or "")[:2000],
            (quote or "")[:1500],
            (content or "")[:20000],
            ref_type,
            ref_id,
            lane,
            json.dumps(tags or [], ensure_ascii=False),
            origin if origin in ("live", "mock", "manual") else "manual",
        ),
    )
    conn.commit()
    return material_id


def update_material(conn: sqlite3.Connection, material_id: str, fields: dict) -> dict:
    allowed = {"title", "summary", "quote", "content", "tags", "lane", "archived", "url", "source_name"}
    sets: list[str] = []
    params: list[object] = []
    for key, value in fields.items():
        if key not in allowed or value is None:
            continue
        if key == "tags":
            sets.append("tags_json=?")
            params.append(json.dumps(list(value), ensure_ascii=False))
        elif key == "archived":
            sets.append("archived=?")
            params.append(1 if value else 0)
        else:
            sets.append(f"{key}=?")
            params.append(value)
    if sets:
        sets.append("updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')")
        conn.execute(f"UPDATE materials SET {', '.join(sets)} WHERE id=?", (*params, material_id))
        conn.commit()
    return get_material(conn, material_id)


# ── builders from radar objects ──


def _first_sentences(text: str, limit: int = 240) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def material_from_signal(conn: sqlite3.Connection, signal_id: str) -> str:
    row = conn.execute(
        "SELECT s.*, so.name AS source_name, so.kind AS source_kind, a.lane, a.why FROM signals s "
        "JOIN sources so ON so.id=s.source_id LEFT JOIN story_assessments a ON a.signal_id=s.id WHERE s.id=?",
        (signal_id,),
    ).fetchone()
    if not row:
        raise NotFound("信号不存在", details={"id": signal_id})
    meta = json.loads(row["metadata_json"] or "{}")
    is_story = row["source_kind"] == "story"
    return create_material(
        conn,
        kind="story" if is_story else "signal",
        title=row["title"] or _first_sentences(row["content"], 80),
        url=row["url"],
        source_name=row["source_name"],
        author=row["author"],
        published_at=row["created_at"],
        summary=meta.get("summary") or _first_sentences(row["content"]),
        quote=_first_sentences(row["content"], 400),
        content=row["content"] or "",
        ref_type="signal",
        ref_id=signal_id,
        lane=row["lane"],
        origin=row["origin"],
    )


def material_from_cluster(conn: sqlite3.Connection, cluster_id: str) -> str:
    c = conn.execute("SELECT * FROM pain_clusters WHERE id=?", (cluster_id,)).fetchone()
    if not c:
        raise NotFound("痛点簇不存在", details={"id": cluster_id})
    quotes = conn.execute(
        "SELECT s.title, s.content, s.url, so.name AS source_name FROM pain_cluster_items i JOIN signals s ON s.id=i.signal_id "
        "JOIN sources so ON so.id=s.source_id WHERE i.cluster_id=? ORDER BY s.created_at DESC LIMIT 5",
        (cluster_id,),
    ).fetchall()
    lines = [
        f"- {_first_sentences(q['content'] or q['title'], 200)} — {q['source_name']} {q['url']}"
        for q in quotes
    ]
    return create_material(
        conn,
        kind="cluster",
        title=c["label"],
        url=None,
        source_name=f"{c['source_count']} 个来源 · {c['signal_count']} 条信号",
        summary=c["summary"] or "",
        quote=_first_sentences(quotes[0]["content"], 400) if quotes else "",
        content="\n".join(lines),
        ref_type="pain_cluster",
        ref_id=cluster_id,
        origin=c["data_mode"] if c["data_mode"] in ("live", "mock") else "live",
    )


def material_from_opportunity(conn: sqlite3.Connection, opportunity_id: str) -> str:
    o = conn.execute("SELECT * FROM opportunities WHERE id=?", (opportunity_id,)).fetchone()
    if not o:
        raise NotFound("机会不存在", details={"id": opportunity_id})
    parts = [
        f"目标用户：{o['target_user'] or ''}",
        f"核心痛点：{o['core_pain'] or ''}",
        f"解法：{o['proposed_solution'] or ''}",
        f"为什么是现在：{o['why_now'] or ''}",
        f"竞品弱点：{o['competitor_weakness'] or ''}",
        f"评分 {o['opportunity_score']:.0f} / 置信 {o['confidence']:.0f}",
    ]
    return create_material(
        conn,
        kind="opportunity",
        title=o["title"],
        source_name="机会雷达",
        summary=o["description"] or "",
        quote=o["core_pain"] or "",
        content="\n".join(parts),
        ref_type="opportunity",
        ref_id=opportunity_id,
        origin=o["data_mode"] if o["data_mode"] in ("live", "mock") else "live",
    )


def material_from_url(conn: sqlite3.Connection, url: str, *, note: str = "") -> str:
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ValidationFailed("请输入 http(s) 链接")
    existing = conn.execute("SELECT id FROM materials WHERE url=? AND archived=0", (url,)).fetchone()
    if existing:
        return existing["id"]
    page = fetch_public_page(url)
    article = extract_article(page.text, url)
    return create_material(
        conn,
        kind="url",
        title=article.title or url,
        url=url,
        source_name=article.site_name,
        author=article.author,
        published_at=iso(article.published),
        summary=article.summary or _first_sentences(article.content),
        quote=_first_sentences(article.content, 400),
        content=(article.content or "") + (f"\n\n备注：{note}" if note else ""),
        origin="manual",
    )
