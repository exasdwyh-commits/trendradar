from __future__ import annotations

import json
import re
import sqlite3
import uuid
from pathlib import Path

from ..grounding import assert_no_new_numeric_claims
from ..llm import chat_json, slot_enabled
from ..snapshot import freeze_publication_snapshot
from .documents import get_document, plain_to_html


PLATFORM_RULES={
    "WECHAT":"3000-5000字深度商业文章；保留完整论证、数据、反方和中国映射；标题克制但有张力。",
    "XIAOHONGSHU":"适合8张以内信息卡：封面问题 + 6个核心观点 + 结论；正文简洁，避免营销腔。",
    "ZHIHU":"以问题驱动的长回答；先给结论，再逐层解释机制、证据与反方。",
    "TOUTIAO":"信息密度高、开头快、段落短；保留商业机制，减少学术化表达。",
    "X":"压缩成英文或中英双语线程式要点；每条只表达一个判断，避免无依据的确定语气。",
}

PLATFORM_SYSTEM="""你是商业内容平台编辑。
你会收到一篇已经确认核心判断的母稿。不要重新发明观点，不补造事实。
根据目标平台重构表达，但保持事实边界、反方证据和中国映射。
输出 JSON：{"title":"","content_text":"","content_html":"","metadata":{}}"""


def create_platform_variant(conn: sqlite3.Connection, document_id: str, platform: str) -> str:
    platform=platform.upper()
    if platform not in PLATFORM_RULES:
        raise ValueError("unsupported platform")
    if not slot_enabled("WRITING_MODEL"):
        raise RuntimeError("WRITING_MODEL not configured")
    doc=get_document(conn,document_id)
    if not doc or not doc.get("current"):
        raise KeyError("document not found")
    payload={
        "platform":platform,
        "platform_rules":PLATFORM_RULES[platform],
        "title":doc["title"],
        "thesis":doc.get("thesis"),
        "master_text":doc["current"].get("plain_text",""),
    }
    data,model=chat_json(
        "WRITING_MODEL",PLATFORM_SYSTEM,json.dumps(payload,ensure_ascii=False),
        conn=conn,task=f"platform_variant:{platform.lower()}",
    )
    vid=uuid.uuid4().hex
    text=str(data.get("content_text") or "")
    generated_title=str(data.get("title") or doc["title"])
    assert_no_new_numeric_claims(
        f"{generated_title}\n{text}",
        [
            doc["title"],doc["current"].get("plain_text",""),
            str(doc.get("thesis") or ""),
            *(f"{e.get('title','')} {e.get('summary','')}" for e in (doc.get("evidence") or [])),
        ],
        context=f"platform variant {platform}",
    )
    html_content=data.get("content_html") or plain_to_html(text)
    conn.execute(
        """
        INSERT INTO platform_variants(
          id,document_id,platform,title,content_text,content_html,metadata_json,status,generated_by
        ) VALUES(?,?,?,?,?,?,?,'READY',?)
        """,
        (
            vid,document_id,platform,generated_title,text,html_content,
            json.dumps(data.get("metadata",{}),ensure_ascii=False),model,
        ),
    )
    conn.commit()
    return vid


def list_publish_center(conn: sqlite3.Connection) -> list[dict]:
    rows=conn.execute(
        """
        SELECT pv.*,d.title master_title,p.status publication_status,p.external_url,p.published_at
        FROM platform_variants pv
        JOIN documents d ON d.id=pv.document_id
        LEFT JOIN publications p ON p.variant_id=pv.id
        ORDER BY pv.updated_at DESC
        """
    ).fetchall()
    result=[]
    for row in rows:
        item=dict(row)
        try:
            item["metadata"]=json.loads(item.pop("metadata_json") or "{}")
        except json.JSONDecodeError:
            item["metadata"]={}
        result.append(item)
    return result


def mark_variant_published(
    conn: sqlite3.Connection,
    variant_id: str,
    external_url: str | None = None,
) -> str:
    row=conn.execute(
        "SELECT * FROM platform_variants WHERE id=?",
        (variant_id,),
    ).fetchone()
    if not row:
        raise KeyError("variant not found")

    document=conn.execute(
        "SELECT * FROM documents WHERE id=?",
        (row["document_id"],),
    ).fetchone()
    if not document:
        raise KeyError("document not found")

    if document["article_id"]:
        article=conn.execute(
            "SELECT status FROM articles WHERE id=?",
            (document["article_id"],),
        ).fetchone()
        if not article or article["status"]!="READY":
            raise ValueError("article must pass Challenger before publication")

    existing=conn.execute(
        "SELECT id FROM publications WHERE variant_id=?",
        (variant_id,),
    ).fetchone()
    if existing:
        publication_id=existing["id"]
        conn.execute(
            """
            UPDATE publications
            SET status='PUBLISHED',published_at=CURRENT_TIMESTAMP,external_url=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (external_url,publication_id),
        )
    else:
        publication_id=uuid.uuid4().hex
        conn.execute(
            """
            INSERT INTO publications(id,variant_id,platform,status,published_at,external_url)
            VALUES(?,?,?,'PUBLISHED',CURRENT_TIMESTAMP,?)
            """,
            (publication_id,variant_id,row["platform"],external_url),
        )
    conn.execute(
        """
        UPDATE platform_variants
        SET status='PUBLISHED',updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (variant_id,),
    )
    conn.commit()
    freeze_publication_snapshot(
        conn,
        document_id=row["document_id"],
        variant_id=variant_id,
        publication_id=publication_id,
        reason="PUBLISHED",
    )
    return publication_id


def export_variant(
    conn: sqlite3.Connection,
    variant_id: str,
    output_dir: str | Path,
) -> Path:
    row=conn.execute(
        "SELECT * FROM platform_variants WHERE id=?",
        (variant_id,),
    ).fetchone()
    if not row:
        raise KeyError("variant not found")
    out=Path(output_dir)
    out.mkdir(parents=True,exist_ok=True)
    safe=re.sub(r"[^\w\u4e00-\u9fff-]+","-",row["title"] or "content").strip("-")[:60]
    if row["platform"]=="WECHAT":
        path=out/f"{safe}-{row['platform'].lower()}.html"
        path.write_text(
            row["content_html"] or plain_to_html(row["content_text"]),
            encoding="utf-8",
        )
    else:
        path=out/f"{safe}-{row['platform'].lower()}.txt"
        path.write_text(
            f"{row['title']}\n\n{row['content_text']}",
            encoding="utf-8",
        )
    return path
