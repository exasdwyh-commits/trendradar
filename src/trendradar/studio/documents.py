"""Documents (母稿) with versions and bound materials. Markdown is the storage format."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta

from ..core.errors import NotFound, ValidationFailed
from ..core.ids import new_id
from ..db.connection import row_to_dict, rows_to_dicts
from .materials import get_material

STATUSES = ("idea", "draft", "ready", "published", "archived")
PLATFORMS = ("wechat", "xiaohongshu", "zhihu", "toutiao", "x")
AUTOSAVE_SNAPSHOT_MINUTES = 15

_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_WORD = re.compile(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*")
_MD_NOISE = re.compile(r"[#*`>\[\]()_~|-]")


def split_leading_h1(markdown: str) -> tuple[str | None, str]:
    """Return (h1_text, body_without_it). The title travels separately from the body everywhere
    (editor preview, exports, platform variants), so a leading H1 would otherwise render twice."""
    first, _, rest = (markdown or "").lstrip().partition("\n")
    if first.startswith("# "):
        return first[2:].strip(), rest.lstrip("\n")
    return None, markdown or ""


def word_count(markdown: str) -> int:
    text = _MD_NOISE.sub(" ", markdown or "")
    return len(_CJK.findall(text)) + len(_WORD.findall(text))


def _data_mode(conn: sqlite3.Connection, document_id: str) -> str:
    origins = {
        r[0]
        for r in conn.execute(
            "SELECT m.origin FROM document_materials dm JOIN materials m ON m.id=dm.material_id WHERE dm.document_id=?",
            (document_id,),
        ).fetchall()
    }
    if not origins:
        return "live"
    if origins == {"mock"}:
        return "mock"
    return "mixed" if "mock" in origins else "live"


def _touch(conn: sqlite3.Connection, document_id: str) -> None:
    conn.execute(
        "UPDATE documents SET data_mode=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
        (_data_mode(conn, document_id), document_id),
    )


def _snapshot(conn: sqlite3.Connection, document_id: str, *, source: str, note: str | None = None) -> int:
    doc = conn.execute(
        "SELECT title, content_md, current_version FROM documents WHERE id=?", (document_id,)
    ).fetchone()
    number = int(doc["current_version"]) + 1
    conn.execute(
        "INSERT INTO document_versions(id,document_id,version_number,title,content_md,source,note,word_count) VALUES(?,?,?,?,?,?,?,?)",
        (
            new_id(),
            document_id,
            number,
            doc["title"],
            doc["content_md"],
            source,
            note,
            word_count(doc["content_md"]),
        ),
    )
    conn.execute("UPDATE documents SET current_version=? WHERE id=?", (number, document_id))
    return number


def create_document(
    conn: sqlite3.Connection,
    *,
    title: str = "",
    content_md: str = "",
    thesis: str = "",
    lane: str | None = None,
    target_platform: str = "wechat",
    seed_material_id: str | None = None,
    status: str = "idea",
    meta: dict | None = None,
) -> str:
    if target_platform not in PLATFORMS:
        raise ValidationFailed("未知目标平台", details={"allowed": PLATFORMS})
    document_id = new_id()
    conn.execute(
        """
        INSERT INTO documents(id,title,status,lane,thesis,target_platform,content_md,word_count,seed_material_id,meta_json)
        VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        (
            document_id,
            (title or "").strip()[:200] or "未命名稿件",
            status if status in STATUSES else "idea",
            lane,
            thesis or "",
            target_platform,
            content_md or "",
            word_count(content_md),
            seed_material_id,
            json.dumps(meta or {}, ensure_ascii=False),
        ),
    )
    if seed_material_id:
        conn.execute(
            "INSERT OR IGNORE INTO document_materials(document_id,material_id,relation) VALUES(?,?,'seed')",
            (document_id, seed_material_id),
        )
    _snapshot(conn, document_id, source="seed", note="新建")
    _touch(conn, document_id)
    conn.commit()
    return document_id


def list_documents(
    conn: sqlite3.Connection, *, status: str | None = None, q: str | None = None, limit: int = 200
) -> list[dict]:
    where, params = ["1=1"], []
    if status:
        if status not in STATUSES:
            raise ValidationFailed("未知状态", details={"allowed": STATUSES})
        where.append("d.status=?")
        params.append(status)
    else:
        where.append("d.status!='archived'")
    if q:
        where.append("(d.title LIKE ? OR d.thesis LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    rows = conn.execute(
        f"""
        SELECT d.id,d.title,d.status,d.lane,d.thesis,d.target_platform,d.word_count,d.data_mode,d.current_version,
               d.created_at,d.updated_at,
               (SELECT COUNT(*) FROM document_materials dm WHERE dm.document_id=d.id) AS material_count,
               (SELECT COUNT(*) FROM platform_variants v WHERE v.document_id=d.id) AS variant_count,
               (SELECT COUNT(*) FROM publications p WHERE p.document_id=d.id) AS publication_count
        FROM documents d WHERE {" AND ".join(where)} ORDER BY d.updated_at DESC LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    return rows_to_dicts(rows)


def get_document(conn: sqlite3.Connection, document_id: str) -> dict:
    doc = row_to_dict(conn.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone())
    if not doc:
        raise NotFound("稿件不存在", details={"id": document_id})
    doc["meta"] = json.loads(doc.pop("meta_json") or "{}")
    materials = rows_to_dicts(
        conn.execute(
            "SELECT m.*, dm.relation, dm.note AS binding_note FROM document_materials dm JOIN materials m ON m.id=dm.material_id "
            "WHERE dm.document_id=? ORDER BY CASE dm.relation WHEN 'seed' THEN 0 WHEN 'support' THEN 1 ELSE 2 END, dm.created_at",
            (document_id,),
        ).fetchall()
    )
    for m in materials:
        m["tags"] = json.loads(m.pop("tags_json") or "[]")
    doc["materials"] = materials
    doc["versions"] = rows_to_dicts(
        conn.execute(
            "SELECT id,version_number,title,source,note,word_count,created_at FROM document_versions WHERE document_id=? "
            "ORDER BY version_number DESC LIMIT 50",
            (document_id,),
        ).fetchall()
    )
    variants = rows_to_dicts(
        conn.execute(
            "SELECT * FROM platform_variants WHERE document_id=? ORDER BY created_at DESC", (document_id,)
        ).fetchall()
    )
    for v in variants:
        v["meta"] = json.loads(v.pop("meta_json") or "{}")
        v["warnings"] = json.loads(v.pop("warnings_json") or "[]")
    doc["variants"] = variants
    doc["publications"] = rows_to_dicts(
        conn.execute(
            "SELECT * FROM publications WHERE document_id=? ORDER BY published_at DESC", (document_id,)
        ).fetchall()
    )
    doc["ai_actions"] = [
        {
            **a,
            "output": json.loads(a.pop("output_json") or "{}"),
            "warnings": json.loads(a.pop("warnings_json") or "[]"),
        }
        for a in rows_to_dicts(
            conn.execute(
                "SELECT id,action,mode,input_excerpt,output_json,model,generated_by,warnings_json,accepted,created_at "
                "FROM ai_actions WHERE document_id=? ORDER BY created_at DESC LIMIT 20",
                (document_id,),
            ).fetchall()
        )
    ]
    return doc


def update_document(
    conn: sqlite3.Connection,
    document_id: str,
    fields: dict,
    *,
    save_mode: str = "autosave",
    note: str | None = None,
) -> dict:
    """Update title/content/thesis/status/etc.

    save_mode='autosave' writes the current text and snapshots at most every AUTOSAVE_SNAPSHOT_MINUTES;
    'manual' snapshots the updated text (a named version); 'ai' snapshots before applying model output.
    """
    current = conn.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
    if not current:
        raise NotFound("稿件不存在", details={"id": document_id})
    allowed = {"title", "content_md", "thesis", "status", "lane", "target_platform"}
    sets, params = [], []
    for key, value in fields.items():
        if key not in allowed or value is None:
            continue
        if key == "status" and value not in STATUSES:
            raise ValidationFailed("未知状态", details={"allowed": STATUSES})
        if key == "target_platform" and value not in PLATFORMS:
            raise ValidationFailed("未知目标平台", details={"allowed": PLATFORMS})
        if key == "title":
            value = (value or "").strip()[:200] or "未命名稿件"
        sets.append(f"{key}=?")
        params.append(value)
    content_changed = (
        "content_md" in fields
        and fields["content_md"] is not None
        and fields["content_md"] != current["content_md"]
    )
    title_changed = (
        "title" in fields and fields["title"] is not None and fields["title"].strip() != current["title"]
    )

    if save_mode == "ai" or (
        save_mode == "autosave" and (content_changed or title_changed) and _snapshot_due(conn, document_id)
    ):
        _snapshot(conn, document_id, source=save_mode if save_mode != "autosave" else "autosave", note=note)

    if sets:
        if "content_md" in fields and fields["content_md"] is not None:
            sets.append("word_count=?")
            params.append(word_count(fields["content_md"]))
        if content_changed and current["status"] == "idea":
            sets.append("status='draft'")
        conn.execute(f"UPDATE documents SET {', '.join(sets)} WHERE id=?", (*params, document_id))
    _touch(conn, document_id)
    if save_mode == "manual":
        _snapshot(conn, document_id, source="manual", note=note)
    conn.commit()
    return get_document(conn, document_id)


def _snapshot_due(conn: sqlite3.Connection, document_id: str) -> bool:
    last = conn.execute(
        "SELECT created_at FROM document_versions WHERE document_id=? ORDER BY version_number DESC LIMIT 1",
        (document_id,),
    ).fetchone()
    if not last:
        return True
    stamp = datetime.fromisoformat(str(last["created_at"]).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return datetime.now(UTC) - stamp >= timedelta(minutes=AUTOSAVE_SNAPSHOT_MINUTES)


def save_version(conn: sqlite3.Connection, document_id: str, note: str | None = None) -> int:
    if not conn.execute("SELECT 1 FROM documents WHERE id=?", (document_id,)).fetchone():
        raise NotFound("稿件不存在", details={"id": document_id})
    number = _snapshot(conn, document_id, source="manual", note=note or "手动保存")
    conn.commit()
    return number


def get_version(conn: sqlite3.Connection, document_id: str, version_number: int) -> dict:
    row = row_to_dict(
        conn.execute(
            "SELECT * FROM document_versions WHERE document_id=? AND version_number=?",
            (document_id, version_number),
        ).fetchone()
    )
    if not row:
        raise NotFound("版本不存在", details={"document_id": document_id, "version": version_number})
    return row


def restore_version(conn: sqlite3.Connection, document_id: str, version_number: int) -> dict:
    version = get_version(conn, document_id, version_number)
    _snapshot(conn, document_id, source="restore", note=f"恢复 v{version_number} 前的快照")
    conn.execute(
        "UPDATE documents SET title=?, content_md=?, word_count=? WHERE id=?",
        (version["title"], version["content_md"], word_count(version["content_md"]), document_id),
    )
    _touch(conn, document_id)
    conn.commit()
    return get_document(conn, document_id)


def bind_material(
    conn: sqlite3.Connection,
    document_id: str,
    material_id: str,
    *,
    relation: str = "support",
    note: str | None = None,
) -> dict:
    if relation not in ("seed", "support", "context"):
        raise ValidationFailed("未知绑定关系")
    get_material(conn, material_id)
    if not conn.execute("SELECT 1 FROM documents WHERE id=?", (document_id,)).fetchone():
        raise NotFound("稿件不存在", details={"id": document_id})
    conn.execute(
        "INSERT INTO document_materials(document_id,material_id,relation,note) VALUES(?,?,?,?) "
        "ON CONFLICT(document_id,material_id) DO UPDATE SET relation=excluded.relation, note=COALESCE(excluded.note, document_materials.note)",
        (document_id, material_id, relation, note),
    )
    _touch(conn, document_id)
    conn.commit()
    return get_document(conn, document_id)


def unbind_material(conn: sqlite3.Connection, document_id: str, material_id: str) -> dict:
    conn.execute(
        "DELETE FROM document_materials WHERE document_id=? AND material_id=?", (document_id, material_id)
    )
    _touch(conn, document_id)
    conn.commit()
    return get_document(conn, document_id)


def delete_document(conn: sqlite3.Connection, document_id: str) -> None:
    conn.execute("DELETE FROM documents WHERE id=?", (document_id,))
    conn.commit()


def seed_markdown(material: dict, *, why: str = "", angles: list[str] | None = None) -> str:
    """Skeleton a new piece starts from when it is extended from a material."""
    lines: list[str] = []
    if why:
        lines += [f"> 核心判断：{why}", ""]
    if angles:
        lines += ["## 可选切口", *[f"- {a}" for a in angles], ""]
    lines += [
        "## 素材",
        f"- {material['title']}" + (f"（{material['source_name']}）" if material.get("source_name") else ""),
    ]
    if material.get("url"):
        lines.append(f"  - 链接：{material['url']}")
    if material.get("quote"):
        lines.append(f"  - 摘录：{material['quote'][:300]}")
    lines += [
        "",
        "## 正文",
        "",
        "（在右侧「AI 助手」生成大纲或初稿，或直接开始写。所有数字请以素材为准。）",
        "",
    ]
    return "\n".join(lines)
