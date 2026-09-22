from __future__ import annotations

import html
import re
import sqlite3
from pathlib import Path


def _article(conn: sqlite3.Connection, article_id: str):
    row = conn.execute(
        """
        SELECT a.*,t.thesis FROM articles a
        JOIN theses t ON t.id=a.thesis_id
        WHERE a.id=?
        """,
        (article_id,),
    ).fetchone()
    if not row:
        raise KeyError("article not found")
    return row


def export_markdown(conn: sqlite3.Connection, article_id: str, output_dir: str | Path) -> Path:
    row = _article(conn, article_id)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", row["title"] or "article").strip("-")[:60]
    path = output / f"{safe or article_id}.md"
    text = f"# {row['title']}\n\n> 核心判断：{row['thesis']}\n\n{row['body'] or ''}\n"
    path.write_text(text, encoding="utf-8")
    return path


def export_wechat_html(conn: sqlite3.Connection, article_id: str, output_dir: str | Path) -> Path:
    row = _article(conn, article_id)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", row["title"] or "article").strip("-")[:60]
    body = html.escape(row["body"] or "")
    paragraphs = "".join(f"<p>{p}</p>" for p in body.split("\n") if p.strip())
    document = f"""<!doctype html><meta charset="utf-8">
<article style="max-width:720px;margin:auto;font-family:-apple-system,BlinkMacSystemFont,'PingFang SC',sans-serif;color:#222;line-height:1.9">
<h1 style="font-size:28px;line-height:1.35">{html.escape(row['title'] or '')}</h1>
<p style="color:#777;font-size:14px">核心判断：{html.escape(row['thesis'])}</p>
{paragraphs}
</article>"""
    path = output / f"{safe or article_id}.html"
    path.write_text(document, encoding="utf-8")
    return path
