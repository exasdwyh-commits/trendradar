from __future__ import annotations

import json
import sqlite3
import uuid

from ..grounding import assert_no_new_numeric_claims
from ..llm import chat_json, slot_enabled
from .documents import get_document


IMAGE_PLAN_SYSTEM="""你是商业深度文章的视觉编辑，不负责生成图片。
你的任务是判断一篇文章真正需要哪些图，而不是为了好看塞图。
优先级：真实数据图 > 机制图/产业链图 > 真实照片/截图 > AI插画。

证据纪律：
- 输入会提供文章已经绑定的 evidence。
- DATA_CHART 必须给 evidence_ids，且只能引用输入里真实存在的 evidence id；没有数据依据就不要建议数据图。
- SCREENSHOT / PHOTO 如果建议使用原始来源截图或真实素材，也应给 evidence_ids。
- DIAGRAM / COVER / ILLUSTRATION 可以不依赖具体 evidence，但不得在 prompt 里捏造数字、公司事实或产品界面。
- AI 插画只能承担概念表达，不能伪装成真实新闻照片或真实产品截图。

每张图说明 placement、type、title、brief、why、aspect_ratio、prompt、evidence_ids。
若不需要某类图就不要建议。总数控制在2-5张。
输出 JSON：{"items":[{"placement":"","type":"COVER|PHOTO|DATA_CHART|DIAGRAM|SCREENSHOT|ILLUSTRATION","title":"","brief":"","why":"","aspect_ratio":"","prompt":"","evidence_ids":[]}]}"""


def create_image_plan(conn: sqlite3.Connection, document_id: str) -> list[dict]:
    if not slot_enabled("WRITING_MODEL"):
        raise RuntimeError("WRITING_MODEL not configured")
    doc=get_document(conn,document_id)
    if not doc or not doc.get("current"):
        raise KeyError("document not found")

    evidence=[
        {
            "id":item["id"],
            "source_id":item["source_id"],
            "role":item["source_role"],
            "relation":item.get("relation"),
            "title":item["title"],
            "summary":item.get("summary") or "",
            "url":item["url"],
        }
        for item in (doc.get("evidence") or [])[:12]
    ]
    allowed_ids={item["id"] for item in evidence}
    evidence_by_id={item["id"]:item for item in evidence}
    payload={
        "title":doc["title"],
        "thesis":doc.get("thesis"),
        "body":doc["current"].get("plain_text",""),
        "evidence":evidence,
    }
    data,model=chat_json(
        "WRITING_MODEL",IMAGE_PLAN_SYSTEM,json.dumps(payload,ensure_ascii=False),
        conn=conn,task="image_plan",
    )
    created=[]
    for item in data.get("items",[])[:5]:
        if not isinstance(item,dict):
            continue
        asset_type=(item.get("type") or "DIAGRAM").upper()
        if asset_type not in {"COVER","PHOTO","DATA_CHART","DIAGRAM","SCREENSHOT","ILLUSTRATION"}:
            asset_type="DIAGRAM"

        raw_ids=item.get("evidence_ids") or []
        if isinstance(raw_ids,str):
            raw_ids=[raw_ids]
        evidence_ids=[
            str(value) for value in raw_ids
            if isinstance(raw_ids,list) and str(value) in allowed_ids
        ]
        evidence_ids=list(dict.fromkeys(evidence_ids))

        if asset_type=="DATA_CHART" and not evidence_ids:
            continue
        assert_no_new_numeric_claims(
            f"{item.get('title','')} {item.get('brief','')} {item.get('prompt','')}",
            [
                doc["current"].get("plain_text",""),
                str(doc.get("thesis") or ""),
                *(f"{e.get('title','')} {e.get('summary','')}" for e in evidence),
            ],
            context="image plan",
        )

        source_url=None
        if evidence_ids and asset_type in {"DATA_CHART","PHOTO","SCREENSHOT"}:
            source_url=evidence_by_id[evidence_ids[0]]["url"]

        aid=uuid.uuid4().hex
        role="COVER" if asset_type=="COVER" else "INLINE"
        conn.execute(
            """
            INSERT INTO media_assets(
              id,document_id,asset_type,role,title,brief,placement,prompt,aspect_ratio,
              source_url,evidence_ids_json,status,generated_by
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,'SUGGESTED',?)
            """,
            (
                aid,document_id,asset_type,role,item.get("title","配图建议"),
                item.get("brief",""),item.get("placement",""),item.get("prompt",""),
                item.get("aspect_ratio","16:9"),source_url,
                json.dumps(evidence_ids,ensure_ascii=False),model,
            ),
        )
        created.append({
            "id":aid,**item,"type":asset_type,
            "evidence_ids":evidence_ids,"source_url":source_url,
        })
    conn.commit()
    return created
