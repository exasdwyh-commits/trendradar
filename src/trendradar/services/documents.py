from __future__ import annotations

import html
import json
import re
import sqlite3
import uuid


def plain_to_html(text: str) -> str:
    parts=[p.strip() for p in re.split(r"\n\s*\n|\n",text or "") if p.strip()]
    return "".join(f"<p>{html.escape(p)}</p>" for p in parts)


def text_to_tiptap(text: str) -> dict:
    content=[]
    for p in [x.strip() for x in (text or "").splitlines() if x.strip()]:
        content.append({"type":"paragraph","content":[{"type":"text","text":p}]})
    return {"type":"doc","content":content or [{"type":"paragraph"}]}


def _latest_version(conn: sqlite3.Connection, document_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM document_versions WHERE document_id=? ORDER BY version_number DESC LIMIT 1",
        (document_id,),
    ).fetchone()


def create_blank_document(conn: sqlite3.Connection, title: str = "未命名文章") -> str:
    document_id=uuid.uuid4().hex
    conn.execute(
        "INSERT INTO documents(id,title,status) VALUES(?,?,'IDEA')",
        (document_id,title.strip() or "未命名文章"),
    )
    save_document(
        conn,document_id,title.strip() or "未命名文章",
        {"type":"doc","content":[{"type":"paragraph"}]},
        "","",source="MANUAL",note="新建空白文章",
    )
    return document_id


def _link_grounded_research_evidence(
    conn: sqlite3.Connection,
    document_id: str,
    candidate_id: str,
) -> None:
    research=conn.execute(
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

    rows=conn.execute(
        """
        SELECT ris.intelligence_id,
          CASE
            WHEN SUM(CASE WHEN ri.kind IN ('FACT','CLAIM') THEN 1 ELSE 0 END)>0
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
        existing=conn.execute(
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
    existing=conn.execute(
        "SELECT id FROM documents WHERE article_id=?",
        (article_id,),
    ).fetchone()
    if existing:
        return existing["id"]

    article=conn.execute("SELECT * FROM articles WHERE id=?",(article_id,)).fetchone()
    if not article:
        raise KeyError("article not found")
    document_id=uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO documents(id,article_id,candidate_id,thesis_id,title,status)
        VALUES(?,?,?,?,?,'DRAFT')
        """,
        (
            document_id,article_id,article["candidate_id"],article["thesis_id"],
            article["title"] or "未命名文章",
        ),
    )
    body=article["body"] or ""
    save_document(
        conn,document_id,article["title"] or "未命名文章",
        text_to_tiptap(body),plain_to_html(body),body,
        source="AI_DRAFT",note="由 Writer 初稿创建",
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
    doc=conn.execute("SELECT * FROM documents WHERE id=?",(document_id,)).fetchone()
    if not doc:
        raise KeyError("document not found")
    if source not in {"AI_DRAFT","MANUAL","AI_EDIT","IMPORT","RESTORE"}:
        source="MANUAL"
    next_version=int(doc["current_version"])+1
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
        UPDATE documents
        SET title=?,current_version=?,
          status=CASE WHEN status='IDEA' THEN 'DRAFT' ELSE status END,
          updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (title.strip() or "未命名文章",next_version,document_id),
    )
    conn.commit()
    return next_version


def restore_version(conn: sqlite3.Connection, document_id: str, version_number: int) -> int:
    row=conn.execute(
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
    doc=conn.execute(
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

    result=dict(doc)
    version=_latest_version(conn,document_id)
    if version:
        current=dict(version)
        current["content_json"]=json.loads(current["content_json"] or "{}")
        result["current"]=current
    else:
        result["current"]=None

    result["versions"]=[
        dict(r) for r in conn.execute(
            """
            SELECT id,version_number,title,source,note,created_at
            FROM document_versions
            WHERE document_id=?
            ORDER BY version_number DESC
            LIMIT 30
            """,
            (document_id,),
        ).fetchall()
    ]

    result["media_assets"]=[]
    for row in conn.execute(
        "SELECT * FROM media_assets WHERE document_id=? ORDER BY created_at DESC",
        (document_id,),
    ).fetchall():
        item=dict(row)
        try:
            item["evidence_ids"]=json.loads(item.pop("evidence_ids_json") or "[]")
        except json.JSONDecodeError:
            item["evidence_ids"]=[]
        result["media_assets"].append(item)

    result["platform_variants"]=[
        dict(r) for r in conn.execute(
            "SELECT * FROM platform_variants WHERE document_id=? ORDER BY updated_at DESC",
            (document_id,),
        ).fetchall()
    ]

    linked=conn.execute(
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
        result["evidence"]=[dict(r) for r in linked]
    elif doc["candidate_id"]:
        candidate=conn.execute(
            "SELECT cluster_id FROM candidates WHERE id=?",
            (doc["candidate_id"],),
        ).fetchone()
        if candidate:
            result["evidence"]=[
                dict(r) for r in conn.execute(
                    """
                    SELECT i.id,i.title,i.url,i.summary,i.kind,i.source_role,i.source_id,i.published_at,
                           'CONTEXT' relation,NULL note
                    FROM cluster_items ci
                    JOIN intelligence i ON i.id=ci.intelligence_id
                    WHERE ci.cluster_id=?
                    ORDER BY i.evidence_score DESC
                    """,
                    (candidate["cluster_id"],),
                ).fetchall()
            ]
        else:
            result["evidence"]=[]
    else:
        result["evidence"]=[]
    return result


def list_documents(conn: sqlite3.Connection) -> list[dict]:
    rows=conn.execute(
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
