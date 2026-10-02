"""Platform variants, exports (Markdown / 公众号-ready inline-styled HTML / plain text) and publication records."""

from __future__ import annotations

import html as html_lib
import json
import re
import sqlite3

from markdown_it import MarkdownIt

from ..core.errors import NotFound, ValidationFailed
from ..core.ids import new_id
from ..db.connection import row_to_dict, rows_to_dicts
from .ai import PLATFORM_NAMES, PLATFORM_RULES, run_action
from .documents import get_document, split_leading_h1

_md = (
    MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False})
    .enable("table")
    .enable("strikethrough")
)

# Inline styles survive the paste into the WeChat editor (class-based CSS does not).
WECHAT_STYLES = {
    "section": "font-size:16px;line-height:1.85;color:#333;letter-spacing:0.3px;word-break:break-word;",
    "h1": "font-size:22px;font-weight:700;margin:32px 0 16px;color:#111;line-height:1.4;",
    "h2": "font-size:19px;font-weight:700;margin:32px 0 14px;padding-left:10px;border-left:4px solid #3b5bdb;color:#111;line-height:1.4;",
    "h3": "font-size:17px;font-weight:700;margin:24px 0 10px;color:#111;",
    "p": "margin:0 0 18px;text-align:justify;",
    "blockquote": "margin:0 0 18px;padding:10px 16px;background:#f5f6fa;border-left:3px solid #c5cae9;color:#555;font-size:15px;",
    "ul": "margin:0 0 18px;padding-left:22px;",
    "ol": "margin:0 0 18px;padding-left:22px;",
    "li": "margin:0 0 6px;",
    "strong": "font-weight:700;color:#111;",
    "em": "font-style:italic;",
    "a": "color:#3b5bdb;text-decoration:none;border-bottom:1px solid #c5cae9;",
    "code": "font-family:Menlo,Consolas,monospace;font-size:14px;background:#f2f3f5;padding:2px 5px;border-radius:3px;",
    "pre": "background:#1e1e1e;color:#eee;padding:14px 16px;border-radius:6px;overflow:auto;font-size:13px;line-height:1.6;margin:0 0 18px;",
    "hr": "border:none;border-top:1px solid #e5e7eb;margin:28px 0;",
    "table": "border-collapse:collapse;width:100%;margin:0 0 18px;font-size:14px;",
    "th": "border:1px solid #e5e7eb;padding:8px;background:#f5f6fa;text-align:left;",
    "td": "border:1px solid #e5e7eb;padding:8px;",
    "img": "max-width:100%;display:block;margin:0 auto 18px;",
}
_TAG_RE = re.compile(r"<(h1|h2|h3|p|blockquote|ul|ol|li|strong|em|a|code|pre|hr|table|th|td|img)(\s[^>]*)?>")


def markdown_to_html(markdown: str) -> str:
    return _md.render(markdown or "")


def markdown_to_wechat_html(markdown: str, *, footer: str | None = None) -> str:
    rendered = markdown_to_html(markdown)

    def add_style(match: re.Match) -> str:
        tag, attrs = match.group(1), match.group(2) or ""
        return f'<{tag}{attrs} style="{WECHAT_STYLES[tag]}">'

    styled = _TAG_RE.sub(add_style, rendered)
    if footer:
        styled += f'<p style="{WECHAT_STYLES["p"]}font-size:13px;color:#888;">{html_lib.escape(footer)}</p>'
    return f'<section style="{WECHAT_STYLES["section"]}">{styled}</section>'


_MD_STRIP = [
    (re.compile(r"^#{1,6}\s*", re.M), ""),
    (re.compile(r"\*\*(.+?)\*\*"), r"\1"),
    (re.compile(r"\*(.+?)\*"), r"\1"),
    (re.compile(r"`(.+?)`"), r"\1"),
    (re.compile(r"!\[[^\]]*\]\([^)]*\)"), ""),
    (re.compile(r"\[([^\]]+)\]\(([^)]+)\)"), r"\1（\2）"),
    (re.compile(r"^>\s?", re.M), ""),
    (re.compile(r"^\s*[-*+]\s+", re.M), "· "),
    (re.compile(r"^-{3,}$", re.M), ""),
]


def markdown_to_plain(markdown: str) -> str:
    text = markdown or ""
    for pattern, repl in _MD_STRIP:
        text = pattern.sub(repl, text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def export_document(
    conn: sqlite3.Connection, document_id: str, fmt: str, *, variant_id: str | None = None
) -> tuple[str, str, str]:
    """Return (content, media_type, filename)."""
    doc = get_document(conn, document_id)
    title, body = doc["title"], doc["content_md"]
    if variant_id:
        variant = next((v for v in doc["variants"] if v["id"] == variant_id), None)
        if not variant:
            raise NotFound("平台版本不存在", details={"id": variant_id})
        title, body = variant["title"], variant["content_md"]
    h1, body = split_leading_h1(body)
    title = title or h1 or ""
    safe = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", title).strip("_")[:60] or "document"
    if fmt == "md":
        return f"# {title}\n\n{body}", "text/markdown; charset=utf-8", f"{safe}.md"
    if fmt == "html":
        return markdown_to_wechat_html(body), "text/html; charset=utf-8", f"{safe}.html"
    if fmt == "txt":
        return f"{title}\n\n{markdown_to_plain(body)}", "text/plain; charset=utf-8", f"{safe}.txt"
    if fmt == "card":
        from .cards import document_card_html

        return document_card_html(title, body), "text/html; charset=utf-8", f"{safe}_card.html"
    raise ValidationFailed("未知导出格式", details={"allowed": ["md", "html", "txt", "card"]})


def create_variant(conn: sqlite3.Connection, document_id: str, platform: str) -> dict:
    if platform not in PLATFORM_RULES:
        raise ValidationFailed("未知平台", details={"allowed": list(PLATFORM_RULES)})
    doc = get_document(conn, document_id)
    if not (doc["content_md"] or "").strip():
        raise ValidationFailed("母稿还是空的，先写正文再生成平台版本")
    result = run_action(conn, document_id, "variant", {"platform": platform})
    out = result["output"]
    from .creation import _hash

    meta = {
        **(out.get("meta") or {}),
        "source_hash": _hash({"title": doc["title"], "content_md": doc["content_md"]}),
    }
    variant_id = new_id()
    conn.execute(
        "INSERT INTO platform_variants(id,document_id,platform,title,content_md,meta_json,generated_by,warnings_json) VALUES(?,?,?,?,?,?,?,?)",
        (
            variant_id,
            document_id,
            platform,
            out.get("title") or doc["title"],
            out.get("content_md") or "",
            json.dumps(meta, ensure_ascii=False),
            result["model"],
            json.dumps(result["warnings"], ensure_ascii=False),
        ),
    )
    conn.commit()
    return get_variant(conn, variant_id)


def get_variant(conn: sqlite3.Connection, variant_id: str) -> dict:
    row = row_to_dict(conn.execute("SELECT * FROM platform_variants WHERE id=?", (variant_id,)).fetchone())
    if not row:
        raise NotFound("平台版本不存在", details={"id": variant_id})
    row["meta"] = json.loads(row.pop("meta_json") or "{}")
    row["warnings"] = json.loads(row.pop("warnings_json") or "[]")
    row["platform_name"] = PLATFORM_NAMES.get(row["platform"], row["platform"])
    row["plain_text"] = markdown_to_plain(row["content_md"])
    return row


def update_variant(conn: sqlite3.Connection, variant_id: str, fields: dict) -> dict:
    sets, params = [], []
    for key in ("title", "content_md"):
        if fields.get(key) is not None:
            sets.append(f"{key}=?")
            params.append(fields[key])
    if sets:
        conn.execute(f"UPDATE platform_variants SET {', '.join(sets)} WHERE id=?", (*params, variant_id))
        conn.commit()
    return get_variant(conn, variant_id)


def delete_variant(conn: sqlite3.Connection, variant_id: str) -> None:
    conn.execute("DELETE FROM platform_variants WHERE id=?", (variant_id,))
    conn.commit()


def record_publication(
    conn: sqlite3.Connection,
    document_id: str,
    *,
    platform: str,
    external_url: str | None = None,
    note: str | None = None,
    variant_id: str | None = None,
) -> dict:
    if platform not in PLATFORM_RULES:
        raise ValidationFailed("未知平台", details={"allowed": list(PLATFORM_RULES)})
    if not conn.execute("SELECT 1 FROM documents WHERE id=?", (document_id,)).fetchone():
        raise NotFound("稿件不存在", details={"id": document_id})
    pub_id = new_id()
    conn.execute(
        "INSERT INTO publications(id,document_id,variant_id,platform,external_url,note) VALUES(?,?,?,?,?,?)",
        (pub_id, document_id, variant_id, platform, (external_url or "").strip() or None, note),
    )
    conn.execute(
        "UPDATE documents SET status='published', updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=? AND status!='archived'",
        (document_id,),
    )
    conn.commit()
    saved = row_to_dict(conn.execute("SELECT * FROM publications WHERE id=?", (pub_id,)).fetchone())
    if saved is None:  # pragma: no cover - inserted just above
        raise RuntimeError("publication was not persisted")
    return saved


def delete_publication(conn: sqlite3.Connection, publication_id: str) -> None:
    conn.execute("DELETE FROM publications WHERE id=?", (publication_id,))
    conn.commit()


def publish_center(conn: sqlite3.Connection) -> dict:
    ready = rows_to_dicts(
        conn.execute(
            """
            SELECT d.id, d.title, d.status, d.target_platform, d.word_count, d.updated_at, d.data_mode,
                   (SELECT GROUP_CONCAT(platform) FROM platform_variants v WHERE v.document_id=d.id) AS variant_platforms,
                   (SELECT GROUP_CONCAT(platform) FROM publications p WHERE p.document_id=d.id) AS published_platforms
            FROM documents d WHERE d.status IN ('ready','published') ORDER BY d.updated_at DESC LIMIT 100
            """
        ).fetchall()
    )
    for r in ready:
        r["variant_platforms"] = (
            sorted(set((r.pop("variant_platforms") or "").split(","))) if r.get("variant_platforms") else []
        )
        r["published_platforms"] = (
            sorted(set((r.pop("published_platforms") or "").split(",")))
            if r.get("published_platforms")
            else []
        )
    publications = rows_to_dicts(
        conn.execute(
            "SELECT p.*, d.title FROM publications p JOIN documents d ON d.id=p.document_id ORDER BY p.published_at DESC LIMIT 100"
        ).fetchall()
    )
    return {"documents": ready, "publications": publications, "platforms": PLATFORM_NAMES}
