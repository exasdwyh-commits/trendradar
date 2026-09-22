from __future__ import annotations

import html
import json
import re
import sqlite3
import uuid
from pathlib import Path

from .llm import chat_json, slot_enabled
from .snapshot import freeze_publication_snapshot


PLATFORM_RULES = {
    "WECHAT": "3000-5000字深度商业文章；保留完整论证、数据、反方和中国映射；标题克制但有张力。",
    "XIAOHONGSHU": "适合8张以内信息卡：封面问题 + 6个核心观点 + 结论；正文简洁，避免营销腔。",
    "ZHIHU": "以问题驱动的长回答；先给结论，再逐层解释机制、证据与反方。",
    "TOUTIAO": "信息密度高、开头快、段落短；保留商业机制，减少学术化表达。",
    "X": "压缩成英文或中英双语线程式要点；每条只表达一个判断，避免无依据的确定语气。",
}

IMAGE_PLAN_SYSTEM = """你是商业深度文章的视觉编辑，不负责生成图片。
你的任务是判断一篇文章真正需要哪些图，而不是为了好看塞图。
优先级：真实数据图 > 机制图/产业链图 > 真实照片/截图 > AI插画。
每张图说明 placement、type、title、brief、why、aspect_ratio、prompt。
若不需要某类图就不要建议。总数控制在2-5张。
输出 JSON：{"items":[{"placement":"","type":"COVER|PHOTO|DATA_CHART|DIAGRAM|SCREENSHOT|ILLUSTRATION","title":"","brief":"","why":"","aspect_ratio":"","prompt":""}]}"""

PLATFORM_SYSTEM = """你是商业内容平台编辑。
你会收到一篇已经确认核心判断的母稿。不要重新发明观点，不补造事实。
根据目标平台重构表达，但保持事实边界、反方证据和中国映射。
输出 JSON：{"title":"","content_text":"","content_html":"","metadata":{}}"""

AI_EDIT_SYSTEM = """你是商业文章的行文编辑，只修改用户选中的文本。
你会收到 selected_text、instruction、上下文、核心判断和这篇文章已经绑定的证据。

纪律：
- 只返回 replacement，不重写未选中的内容。
- 不得新增证据中不存在的事实、数字、公司动作或因果。
- 如果 instruction 要求补事实而证据不支持，保持事实边界，并在 warning 说明。
- 可以改结构、压缩、增强逻辑、降低AI腔、加强反方表达，但不能改变已确认 thesis 的含义。
- used_evidence_ids 只能使用输入 evidence 中真实存在的 id。
输出 JSON：
{"replacement":"","used_evidence_ids":[],"warning":""}
"""

def _plain_to_html(text: str) -> str:
    parts = [p.strip() for p in re.split(r"\n\s*\n|\n", text or "") if p.strip()]
    return "".join(f"<p>{html.escape(p)}</p>" for p in parts)


def _text_to_tiptap(text: str) -> dict:
    content = []
    for p in [x.strip() for x in (text or "").splitlines() if x.strip()]:
        content.append({"type":"paragraph","content":[{"type":"text","text":p}]})
    return {"type":"doc","content":content or [{"type":"paragraph"}]}


def _latest_version(conn: sqlite3.Connection, document_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM document_versions WHERE document_id=? ORDER BY version_number DESC LIMIT 1",
        (document_id,),
    ).fetchone()


def create_blank_document(conn: sqlite3.Connection, title: str = "未命名文章") -> str:
    document_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO documents(id,title,status) VALUES(?,?,'IDEA')",
        (document_id,title.strip() or "未命名文章"),
    )
    save_document(
        conn, document_id, title.strip() or "未命名文章",
        {"type":"doc","content":[{"type":"paragraph"}]},
        "", "", source="MANUAL", note="新建空白文章",
    )
    return document_id


def _link_grounded_research_evidence(
    conn: sqlite3.Connection,
    document_id: str,
    candidate_id: str,
) -> None:
    research = conn.execute(
        """
        SELECT id FROM research
        WHERE candidate_id=?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (candidate_id,),
    ).fetchone()
    if not research:
        return

    rows = conn.execute(
        """
        SELECT ris.intelligence_id,
          CASE
            WHEN SUM(CASE WHEN ri.kind IN ('FACT','CLAIM') THEN 1 ELSE 0 END) > 0
            THEN 'SUPPORT'
            ELSE 'CONTEXT'
          END relation
        FROM research_items ri
        JOIN research_item_sources ris ON ris.research_item_id=ri.id
        WHERE ri.research_id=?
        GROUP BY ris.intelligence_id
        """,
        (research["id"],),
    ).fetchall()
    for row in rows:
        existing = conn.execute(
            """
            SELECT id FROM evidence_links
            WHERE document_id=? AND intelligence_id=? AND text_anchor IS NULL
            """,
            (document_id,row["intelligence_id"]),
        ).fetchone()
        if existing:
            continue
        conn.execute(
            """
            INSERT INTO evidence_links(
              id,document_id,intelligence_id,text_anchor,relation,note
            ) VALUES(?,?,?,NULL,?,?)
            """,
            (
                uuid.uuid4().hex,document_id,row["intelligence_id"],row["relation"],
                "由最新研究包自动绑定",
            ),
        )


def ensure_document_for_article(conn: sqlite3.Connection, article_id: str) -> str:
    existing = conn.execute("SELECT id FROM documents WHERE article_id=?", (article_id,)).fetchone()
    if existing:
        return existing["id"]

    article = conn.execute("SELECT * FROM articles WHERE id=?", (article_id,)).fetchone()
    if not article:
        raise KeyError("article not found")
    document_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO documents(id,article_id,candidate_id,thesis_id,title,status)
        VALUES(?,?,?,?,?,'DRAFT')
        """,
        (document_id,article_id,article["candidate_id"],article["thesis_id"],article["title"] or "未命名文章"),
    )
    body = article["body"] or ""
    save_document(
        conn, document_id, article["title"] or "未命名文章",
        _text_to_tiptap(body), _plain_to_html(body), body,
        source="AI_DRAFT", note="由 Writer 初稿创建",
    )
    _link_grounded_research_evidence(conn,document_id,article["candidate_id"])
    conn.commit()
    return document_id


def save_document(
    conn: sqlite3.Connection,
    document_id: str,
    title: str,
    content_json: dict,
    content_html: str,
    plain_text: str,
    source: str = "MANUAL",
    note: str | None = None,
) -> int:
    doc = conn.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
    if not doc:
        raise KeyError("document not found")
    if source not in {"AI_DRAFT","MANUAL","AI_EDIT","IMPORT","RESTORE"}:
        source = "MANUAL"
    next_version = int(doc["current_version"]) + 1
    conn.execute(
        """
        INSERT INTO document_versions(
          id,document_id,version_number,title,content_json,content_html,plain_text,source,note
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (
            uuid.uuid4().hex,document_id,next_version,title.strip() or "未命名文章",
            json.dumps(content_json or {},ensure_ascii=False),content_html or "",plain_text or "",
            source,note,
        ),
    )
    conn.execute(
        """
        UPDATE documents SET title=?,current_version=?,status=CASE WHEN status='IDEA' THEN 'DRAFT' ELSE status END,
          updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (title.strip() or "未命名文章",next_version,document_id),
    )
    conn.commit()
    return next_version


def restore_version(conn: sqlite3.Connection, document_id: str, version_number: int) -> int:
    row = conn.execute(
        "SELECT * FROM document_versions WHERE document_id=? AND version_number=?",
        (document_id,version_number),
    ).fetchone()
    if not row:
        raise KeyError("version not found")
    return save_document(
        conn,document_id,row["title"],json.loads(row["content_json"] or "{}"),
        row["content_html"],row["plain_text"],source="RESTORE",
        note=f"恢复自 v{version_number}",
    )


def get_document(conn: sqlite3.Connection, document_id: str) -> dict | None:
    doc = conn.execute(
        """
        SELECT d.*,c.title candidate_title,t.thesis
        FROM documents d
        LEFT JOIN candidates c ON c.id=d.candidate_id
        LEFT JOIN theses t ON t.id=d.thesis_id
        WHERE d.id=?
        """,
        (document_id,),
    ).fetchone()
    if not doc:
        return None
    result = dict(doc)
    version = _latest_version(conn,document_id)
    if version:
        v = dict(version)
        v["content_json"] = json.loads(v["content_json"] or "{}")
        result["current"] = v
    else:
        result["current"] = None
    result["versions"] = [
        dict(r) for r in conn.execute(
            """
            SELECT id,version_number,title,source,note,created_at
            FROM document_versions WHERE document_id=?
            ORDER BY version_number DESC LIMIT 30
            """,
            (document_id,),
        ).fetchall()
    ]
    result["media_assets"] = [
        dict(r) for r in conn.execute(
            "SELECT * FROM media_assets WHERE document_id=? ORDER BY created_at DESC",
            (document_id,),
        ).fetchall()
    ]
    result["platform_variants"] = [
        dict(r) for r in conn.execute(
            "SELECT * FROM platform_variants WHERE document_id=? ORDER BY updated_at DESC",
            (document_id,),
        ).fetchall()
    ]
    linked = conn.execute(
        """
        SELECT i.id,i.title,i.url,i.summary,i.kind,i.source_role,i.source_id,i.published_at,
               el.relation,el.note
        FROM evidence_links el
        JOIN intelligence i ON i.id=el.intelligence_id
        WHERE el.document_id=?
        ORDER BY CASE el.relation WHEN 'SUPPORT' THEN 0 WHEN 'COUNTER' THEN 1 ELSE 2 END,
                 i.evidence_score DESC
        """,
        (document_id,),
    ).fetchall()
    if linked:
        result["evidence"] = [dict(r) for r in linked]
    elif doc["candidate_id"]:
        candidate = conn.execute(
            "SELECT cluster_id FROM candidates WHERE id=?",
            (doc["candidate_id"],),
        ).fetchone()
        if candidate:
            result["evidence"] = [
                dict(r) for r in conn.execute(
                    """
                    SELECT i.id,i.title,i.url,i.summary,i.kind,i.source_role,i.source_id,i.published_at,
                           'CONTEXT' relation,NULL note
                    FROM cluster_items ci JOIN intelligence i ON i.id=ci.intelligence_id
                    WHERE ci.cluster_id=? ORDER BY i.evidence_score DESC
                    """,
                    (candidate["cluster_id"],),
                ).fetchall()
            ]
        else:
            result["evidence"] = []
    else:
        result["evidence"] = []
    return result


def list_documents(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT d.*,c.title candidate_title,t.thesis,
          (SELECT COUNT(*) FROM platform_variants pv WHERE pv.document_id=d.id) variant_count
        FROM documents d
        LEFT JOIN candidates c ON c.id=d.candidate_id
        LEFT JOIN theses t ON t.id=d.thesis_id
        ORDER BY d.updated_at DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def edit_selection(
    conn: sqlite3.Connection,
    document_id: str,
    selected_text: str,
    instruction: str,
    before_context: str = "",
    after_context: str = "",
) -> dict:
    if not slot_enabled("WRITING_MODEL"):
        raise RuntimeError("WRITING_MODEL not configured")
    selected_text = (selected_text or "").strip()
    instruction = (instruction or "").strip()
    if not selected_text:
        raise ValueError("selected_text is required")
    if not instruction:
        raise ValueError("instruction is required")
    if len(selected_text) > 6000:
        raise ValueError("selected_text is too long")

    doc = get_document(conn,document_id)
    if not doc or not doc.get("current"):
        raise KeyError("document not found")
    evidence = [
        {
            "id": item["id"],
            "source_id": item["source_id"],
            "role": item["source_role"],
            "relation": item.get("relation"),
            "title": item["title"],
            "summary": item.get("summary") or "",
        }
        for item in (doc.get("evidence") or [])[:12]
    ]
    payload = {
        "title": doc["title"],
        "thesis": doc.get("thesis"),
        "selected_text": selected_text,
        "instruction": instruction,
        "before_context": (before_context or "")[-1200:],
        "after_context": (after_context or "")[:1200],
        "evidence": evidence,
    }
    data,model = chat_json(
        "WRITING_MODEL",
        AI_EDIT_SYSTEM,
        json.dumps(payload,ensure_ascii=False),
        conn=conn,
        task="selection_edit",
    )
    replacement = str(data.get("replacement") or "").strip()
    if not replacement:
        raise ValueError("model returned empty replacement")
    allowed = {item["id"] for item in evidence}
    used = data.get("used_evidence_ids") or []
    if isinstance(used,str):
        used=[used]
    used = [str(x) for x in used if str(x) in allowed] if isinstance(used,list) else []
    return {
        "replacement": replacement,
        "used_evidence_ids": list(dict.fromkeys(used)),
        "warning": str(data.get("warning") or "").strip(),
        "model": model,
    }


def create_image_plan(conn: sqlite3.Connection, document_id: str) -> list[dict]:
    if not slot_enabled("WRITING_MODEL"):
        raise RuntimeError("WRITING_MODEL not configured")
    doc = get_document(conn,document_id)
    if not doc or not doc.get("current"):
        raise KeyError("document not found")
    payload = {
        "title":doc["title"],
        "thesis":doc.get("thesis"),
        "body":doc["current"].get("plain_text",""),
    }
    data,model = chat_json(
        "WRITING_MODEL", IMAGE_PLAN_SYSTEM, json.dumps(payload,ensure_ascii=False),
        conn=conn, task="image_plan"
    )
    created=[]
    for item in data.get("items",[])[:5]:
        asset_type=(item.get("type") or "DIAGRAM").upper()
        if asset_type not in {"COVER","PHOTO","DATA_CHART","DIAGRAM","SCREENSHOT","ILLUSTRATION"}:
            asset_type="DIAGRAM"
        aid=uuid.uuid4().hex
        role="COVER" if asset_type=="COVER" else "INLINE"
        conn.execute(
            """
            INSERT INTO media_assets(
              id,document_id,asset_type,role,title,brief,placement,prompt,aspect_ratio,status,generated_by
            ) VALUES(?,?,?,?,?,?,?,?,?,'SUGGESTED',?)
            """,
            (
                aid,document_id,asset_type,role,item.get("title","配图建议"),
                item.get("brief",""),item.get("placement",""),item.get("prompt",""),
                item.get("aspect_ratio","16:9"),model,
            ),
        )
        created.append({"id":aid,**item,"type":asset_type})
    conn.commit()
    return created


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
        "WRITING_MODEL", PLATFORM_SYSTEM, json.dumps(payload,ensure_ascii=False),
        conn=conn, task=f"platform_variant:{platform.lower()}"
    )
    vid=uuid.uuid4().hex
    text=data.get("content_text","")
    html_content=data.get("content_html") or _plain_to_html(text)
    conn.execute(
        """
        INSERT INTO platform_variants(
          id,document_id,platform,title,content_text,content_html,metadata_json,status,generated_by
        ) VALUES(?,?,?,?,?,?,?,'READY',?)
        """,
        (
            vid,document_id,platform,data.get("title") or doc["title"],text,html_content,
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
    for r in rows:
        item=dict(r)
        try:
            item["metadata"]=json.loads(item.pop("metadata_json") or "{}")
        except json.JSONDecodeError:
            item["metadata"]={}
        result.append(item)
    return result


def mark_variant_published(conn: sqlite3.Connection, variant_id: str, external_url: str | None = None) -> str:
    row=conn.execute("SELECT * FROM platform_variants WHERE id=?",(variant_id,)).fetchone()
    if not row:
        raise KeyError("variant not found")

    document=conn.execute("SELECT * FROM documents WHERE id=?",(row["document_id"],)).fetchone()
    if not document:
        raise KeyError("document not found")

    # AI-generated editorial flows must pass Challenger before publication.
    # A blank/manual document has no article_id and remains fully user-controlled.
    if document["article_id"]:
        article=conn.execute("SELECT status FROM articles WHERE id=?",(document["article_id"],)).fetchone()
        if not article or article["status"]!="READY":
            raise ValueError("article must pass Challenger before publication")

    existing=conn.execute("SELECT id FROM publications WHERE variant_id=?",(variant_id,)).fetchone()
    if existing:
        pid=existing["id"]
        conn.execute(
            """
            UPDATE publications SET status='PUBLISHED',published_at=CURRENT_TIMESTAMP,external_url=?,
              updated_at=CURRENT_TIMESTAMP WHERE id=?
            """,
            (external_url,pid),
        )
    else:
        pid=uuid.uuid4().hex
        conn.execute(
            """
            INSERT INTO publications(id,variant_id,platform,status,published_at,external_url)
            VALUES(?,?,?,'PUBLISHED',CURRENT_TIMESTAMP,?)
            """,
            (pid,variant_id,row["platform"],external_url),
        )
    conn.execute(
        "UPDATE platform_variants SET status='PUBLISHED',updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (variant_id,),
    )
    conn.commit()
    freeze_publication_snapshot(
        conn,
        document_id=row["document_id"],
        variant_id=variant_id,
        publication_id=pid,
        reason="PUBLISHED",
    )
    return pid


def export_variant(conn: sqlite3.Connection, variant_id: str, output_dir: str | Path) -> Path:
    row=conn.execute("SELECT * FROM platform_variants WHERE id=?",(variant_id,)).fetchone()
    if not row:
        raise KeyError("variant not found")
    out=Path(output_dir)
    out.mkdir(parents=True,exist_ok=True)
    safe=re.sub(r"[^\w\u4e00-\u9fff-]+","-",row["title"] or "content").strip("-")[:60]
    if row["platform"]=="WECHAT":
        path=out/f"{safe}-{row['platform'].lower()}.html"
        path.write_text(row["content_html"] or _plain_to_html(row["content_text"]),encoding="utf-8")
    else:
        path=out/f"{safe}-{row['platform'].lower()}.txt"
        path.write_text(f"{row['title']}\n\n{row['content_text']}",encoding="utf-8")
    return path
