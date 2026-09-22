from __future__ import annotations

import json
import sqlite3

from ..grounding import assert_no_new_numeric_claims
from ..llm import chat_json, slot_enabled
from .documents import get_document


AI_EDIT_SYSTEM="""你是商业文章的行文编辑，只修改用户选中的文本。
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
    selected_text=(selected_text or "").strip()
    instruction=(instruction or "").strip()
    if not selected_text:
        raise ValueError("selected_text is required")
    if not instruction:
        raise ValueError("instruction is required")
    if len(selected_text)>6000:
        raise ValueError("selected_text is too long")

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
        }
        for item in (doc.get("evidence") or [])[:12]
    ]
    payload={
        "title":doc["title"],
        "thesis":doc.get("thesis"),
        "selected_text":selected_text,
        "instruction":instruction,
        "before_context":(before_context or "")[-1200:],
        "after_context":(after_context or "")[:1200],
        "evidence":evidence,
    }
    data,model=chat_json(
        "WRITING_MODEL",AI_EDIT_SYSTEM,json.dumps(payload,ensure_ascii=False),
        conn=conn,task="selection_edit",
    )
    replacement=str(data.get("replacement") or "").strip()
    if not replacement:
        raise ValueError("model returned empty replacement")
    assert_no_new_numeric_claims(
        replacement,
        [
            selected_text,before_context,after_context,
            str(doc.get("thesis") or ""),
            *(f"{e.get('title','')} {e.get('summary','')}" for e in evidence),
        ],
        context="selection edit",
    )
    allowed={item["id"] for item in evidence}
    used=data.get("used_evidence_ids") or []
    if isinstance(used,str):
        used=[used]
    used=[str(x) for x in used if str(x) in allowed] if isinstance(used,list) else []
    return {
        "replacement":replacement,
        "used_evidence_ids":list(dict.fromkeys(used)),
        "warning":str(data.get("warning") or "").strip(),
        "model":model,
    }
