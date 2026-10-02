"""Evidence-backed editorial planning, independent outlines and section proposals."""

from __future__ import annotations

import hashlib
import json
import sqlite3

from ..core.errors import NotFound, SourceError, ValidationFailed
from ..core.ids import new_id
from .ai import BASE_SYSTEM, number_warnings, writing_provider, writing_slot
from .documents import get_document, word_count

PLAN_DEFAULTS = {
    "audience": "",
    "question": "",
    "proposition": "",
    "unique_angle": "",
    "counterargument": "",
    "gaps": "",
    "author_notes": "",
    "style": "",
    "examples": "",
    "forbidden": "",
    "article_type": "商业分析",
    "target_words": 2000,
    "sections": [],
    "outline_confirmed": False,
}


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _material_hash(material: dict) -> str:
    return _hash(
        {
            key: material.get(key)
            for key in ("title", "url", "published_at", "content", "summary", "quote", "origin")
        }
    )


def get_workspace(conn: sqlite3.Connection, document_id: str) -> dict:
    doc = get_document(conn, document_id)
    row = conn.execute("SELECT * FROM document_workspaces WHERE document_id=?", (document_id,)).fetchone()
    plan = {**PLAN_DEFAULTS, **(json.loads(row["data_json"]) if row else {})}
    by_id = {material["id"]: material for material in doc["materials"]}
    excerpts = []
    for row_excerpt in conn.execute(
        "SELECT * FROM document_excerpts WHERE document_id=? ORDER BY created_at,id", (document_id,)
    ):
        item = dict(row_excerpt)
        material = by_id.get(item["material_id"])
        item["stale"] = not material or _material_hash(material) != item["source_hash"]
        excerpts.append(item)
    body = doc["content_md"]
    checks = [
        {"id": "body", "ok": word_count(body) >= 100, "label": "正文至少 100 字（仅检查是否仍为空白或骨架）"},
        {
            "id": "placeholders",
            "ok": not any(marker in body for marker in ("【待补充", "（在右侧", "（待补充")),
            "label": "清理待补充与写作提示",
        },
        {
            "id": "origin",
            "ok": doc["data_mode"] != "mock" and doc["data_mode"] != "mixed",
            "label": "稿件不含演示素材",
        },
        {
            "id": "evidence",
            "ok": bool(excerpts) and all(not item["stale"] for item in excerpts),
            "label": "已有可追溯且未过期的证据摘录",
        },
        {"id": "proposition", "ok": bool(plan["proposition"].strip()), "label": "已明确核心判断"},
        {"id": "outline", "ok": bool(plan["outline_confirmed"]), "label": "大纲已确认"},
    ]
    numbers = number_warnings(body, [item["quote"] for item in excerpts]) if excerpts else []
    checks.append(
        {
            "id": "numbers",
            "ok": not numbers,
            "label": "数字写法与摘录一致（不等同于事实核验）",
            "details": numbers,
        }
    )
    checks.append(
        {
            "id": "source_links",
            "ok": bool(excerpts) and all(item["source_url"] for item in excerpts),
            "label": "证据已附原始链接（个人笔记请人工核对）",
        }
    )
    variants = doc["variants"]
    checks.append(
        {
            "id": "variants",
            "ok": all(
                item.get("meta", {}).get("source_hash") == _hash({"title": doc["title"], "content_md": body})
                for item in variants
            ),
            "label": "平台版本基于最新母稿（旧版本请重新生成或人工核对）",
        }
    )
    return {"plan": plan, "revision": row["revision"] if row else 0, "excerpts": excerpts, "checks": checks}


def _save(conn, document_id: str, plan: dict, revision: int) -> None:
    cur = conn.execute(
        "INSERT INTO document_workspaces(document_id,data_json,revision) VALUES(?,?,?) ON CONFLICT(document_id) DO UPDATE SET data_json=excluded.data_json,revision=excluded.revision,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE document_workspaces.revision=?",
        (document_id, json.dumps(plan, ensure_ascii=False), revision + 1, revision),
    )
    if cur.rowcount != 1:
        conn.rollback()
        raise ValidationFailed("创作规划已更新，请刷新后再操作；本次修改未覆盖新内容。")
    conn.commit()


def _current(conn, document_id: str, revision: int) -> dict:
    state = get_workspace(conn, document_id)
    if state["revision"] != revision:
        raise ValidationFailed("创作规划已更新，请刷新后再操作；本次修改未覆盖新内容。")
    return state


def save_workspace(conn, document_id: str, changes: dict, revision: int) -> dict:
    state = _current(conn, document_id, revision)
    plan = state["plan"]
    allowed = set(PLAN_DEFAULTS) - {"outline_confirmed"}
    if set(changes) - allowed:
        raise ValidationFailed("未知规划字段")
    for key, value in changes.items():
        if key not in ("sections", "target_words") and (not isinstance(value, str) or len(value) > 8000):
            raise ValidationFailed("规划文字必须为文本，且不超过 8000 字符")
    words = changes.get("target_words", plan["target_words"])
    if not isinstance(words, int) or not 100 <= words <= 20000:
        raise ValidationFailed("目标字数应为 100–20000")
    sections = changes.get("sections", plan["sections"])
    if not isinstance(sections, list) or len(sections) > 20:
        raise ValidationFailed("大纲最多 20 节")
    known = {item["id"] for item in state["excerpts"]}
    normalised, ids = [], set()
    for section in sections:
        if not isinstance(section, dict):
            raise ValidationFailed("章节必须为对象")
        sid = section.get("id", new_id())
        if not isinstance(sid, str) or len(sid) > 100:
            raise ValidationFailed("章节 ID 无效")
        if sid in ids:
            raise ValidationFailed("章节 ID 不能重复")
        ids.add(sid)
        title, goal, content = (
            section.get("title", ""),
            section.get("goal", ""),
            section.get("content_md", ""),
        )
        if (
            not all(isinstance(value, str) for value in (title, goal, content))
            or not title.strip()
            or len(title) > 200
            or len(goal) > 2000
            or len(content) > 30000
        ):
            raise ValidationFailed("章节需有标题，且文字长度不超过限制")
        evidence_ids = section.get("evidence_ids", [])
        if (
            not isinstance(evidence_ids, list)
            or not all(isinstance(eid, str) for eid in evidence_ids)
            or set(evidence_ids) - known
        ):
            raise ValidationFailed("章节证据必须来自本稿的摘录")
        target = section.get("target_words", 400)
        if not isinstance(target, int) or not 50 <= target <= 5000:
            raise ValidationFailed("章节目标字数应为 50–5000")
        normalised.append(
            {
                "id": sid,
                "title": title.strip(),
                "goal": goal,
                "evidence_ids": list(dict.fromkeys(evidence_ids)),
                "target_words": target,
                "content_md": content,
            }
        )

    def structure(items):
        return [{key: value for key, value in item.items() if key != "content_md"} for item in items]

    changed = any(plan[key] != value for key, value in changes.items() if key != "sections") or structure(
        normalised
    ) != structure(plan["sections"])
    plan = {**plan, **changes, "sections": normalised}
    if changed:
        plan["outline_confirmed"] = False
    _save(conn, document_id, plan, revision)
    return get_workspace(conn, document_id)


def confirm_outline(conn, document_id: str, revision: int) -> dict:
    state = _current(conn, document_id, revision)
    if not state["plan"]["sections"]:
        raise ValidationFailed("先添加至少一节大纲")
    state["plan"]["outline_confirmed"] = True
    _save(conn, document_id, state["plan"], revision)
    return get_workspace(conn, document_id)


def add_excerpt(
    conn, document_id: str, material_id: str, fact: str, quote: str, note: str = "", stance: str = "support"
) -> dict:
    doc = get_document(conn, document_id)
    material = next((item for item in doc["materials"] if item["id"] == material_id), None)
    if not material:
        raise ValidationFailed("请先将素材绑定到本稿")
    quote = quote.strip()
    if not fact.strip() or not quote or len(quote) > 6000 or stance not in ("support", "counter", "context"):
        raise ValidationFailed("摘录需要事实说明、原文和有效立场，原文最多 6000 字符")
    if not any(quote in (material.get(key) or "") for key in ("content", "summary", "quote")):
        raise ValidationFailed("摘录必须是素材中的原文片段，请直接复制原文；个人判断请写在备注。")
    eid = new_id()
    conn.execute(
        "INSERT INTO document_excerpts(id,document_id,material_id,fact,quote,note,stance,source_hash,source_title,source_url,source_date,origin) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            eid,
            document_id,
            material_id,
            fact,
            quote,
            note,
            stance,
            _material_hash(material),
            material["title"],
            material.get("url"),
            material.get("published_at"),
            material["origin"],
        ),
    )
    conn.commit()
    return next(item for item in get_workspace(conn, document_id)["excerpts"] if item["id"] == eid)


def delete_excerpt(conn, document_id: str, excerpt_id: str, revision: int) -> dict:
    state = _current(conn, document_id, revision)
    if not any(item["id"] == excerpt_id for item in state["excerpts"]):
        raise NotFound("摘录不存在")
    for section in state["plan"]["sections"]:
        section["evidence_ids"] = [eid for eid in section["evidence_ids"] if eid != excerpt_id]
    state["plan"]["outline_confirmed"] = False
    conn.execute("DELETE FROM document_excerpts WHERE id=? AND document_id=?", (excerpt_id, document_id))
    _save(conn, document_id, state["plan"], revision)
    return get_workspace(conn, document_id)


def _section_context(state: dict, sid: str) -> dict:
    plan = state["plan"]
    section = next((item for item in plan["sections"] if item["id"] == sid), None)
    if not section:
        raise NotFound("章节不存在")
    evidence = [item for item in state["excerpts"] if item["id"] in section["evidence_ids"]]
    if any(item["stale"] for item in evidence):
        raise ValidationFailed("本节证据已变化或素材已解除绑定，请核对后重新摘录")
    if sum(len(item["quote"]) for item in evidence) > 30000:
        raise ValidationFailed("本节摘录超过 30000 字符，请减少无关证据后生成")
    return {
        "plan": {key: value for key, value in plan.items() if key not in ("sections", "outline_confirmed")},
        "section": section,
        "outline": [{"title": item["title"], "goal": item["goal"]} for item in plan["sections"]],
        "evidence": evidence,
    }


def _proposal(conn, doc: dict, task: str, context: dict, instruction: str) -> dict:
    payload = json.dumps({"instruction": instruction, **context}, ensure_ascii=False)
    if len(payload) > 80000:
        raise ValidationFailed("本次输入超过 80000 字符，请精简规划、正文或证据后重试；资料未被截断")
    try:
        data, model = writing_provider(doc["data_mode"]).chat_json(
            writing_slot(),
            BASE_SYSTEM,
            payload,
            task=task,
            conn=conn,
        )
    except RuntimeError as exc:
        raise SourceError("写作服务暂时不可用，请稍后重试；原稿已保留。") from exc
    if not isinstance(data, dict):
        raise ValidationFailed("模型返回格式无效")
    warnings = number_warnings(
        str(data),
        [item["quote"] for item in context["evidence"]]
        + [
            context["plan"].get("author_notes", ""),
            context.get("content_md", ""),
            context.get("section", {}).get("content_md", ""),
        ],
    )
    if not context["evidence"]:
        warnings.append("没有选择证据摘录：事实缺口应标记待补充，请核实后采用。")
    if model == "fixture":
        warnings.insert(0, "演示模板：本次未调用真实模型，输出仅用于体验流程。")
    return {
        "output": data,
        "model": model,
        "generated_by": "fixture" if model == "fixture" else "model",
        "warnings": warnings,
        "input_hash": _hash(context),
        "input_scope": {
            "evidence_ids": [item["id"] for item in context["evidence"]],
            "quote_characters": sum(len(item["quote"]) for item in context["evidence"]),
            "body_characters": len(context.get("content_md", "")),
        },
    }


def _record(conn, did: str, action: str, result: dict) -> dict:
    aid = new_id()
    conn.execute(
        "INSERT INTO ai_actions(id,document_id,action,input_excerpt,output_json,model,generated_by,warnings_json) VALUES(?,?,?,?,?,?,?,?)",
        (
            aid,
            did,
            action,
            result["input_hash"],
            json.dumps(result, ensure_ascii=False),
            result["model"],
            result["generated_by"],
            json.dumps(result["warnings"], ensure_ascii=False),
        ),
    )
    conn.commit()
    return {"id": aid, **result}


def generate_section(conn, document_id: str, sid: str, revision: int, instruction: str = "") -> dict:
    state = _current(conn, document_id, revision)
    if not state["plan"]["outline_confirmed"]:
        raise ValidationFailed("请先保存并确认大纲，再生成章节")
    context = _section_context(state, sid)
    result = _proposal(
        conn,
        get_document(conn, document_id),
        "studio_section",
        context,
        '只写指定章节的正文，不重复标题，不输出其他章节。遵循读者、目标字数和作者风格；事实使用摘录并以[来源](URL)标注，个人判断明确为判断，缺少证据用【待补充】。返回 JSON {"content_md":"正文"}。用户补充要求：'
        + instruction,
    )
    if (
        not isinstance(result["output"].get("content_md"), str)
        or not result["output"]["content_md"].strip()
        or len(result["output"]["content_md"]) > 30000
    ):
        raise ValidationFailed("模型未返回有效章节")
    result["section_id"] = sid
    result["revision"] = revision
    return _record(conn, document_id, "section", result)


def adopt_section(conn, document_id: str, sid: str, action_id: str, revision: int) -> dict:
    state = _current(conn, document_id, revision)
    row = conn.execute(
        "SELECT output_json FROM ai_actions WHERE id=? AND document_id=? AND action='section'",
        (action_id, document_id),
    ).fetchone()
    if not row:
        raise NotFound("章节候选稿不存在")
    result = json.loads(row["output_json"])
    if result["section_id"] != sid or result["input_hash"] != _hash(_section_context(state, sid)):
        raise ValidationFailed("候选稿所依据的规划或证据已变化，请重新生成")
    sections = [
        {**item, "content_md": result["output"]["content_md"]} if item["id"] == sid else item
        for item in state["plan"]["sections"]
    ]
    updated = save_workspace(conn, document_id, {"sections": sections}, revision)
    conn.execute("UPDATE ai_actions SET accepted=1 WHERE id=?", (action_id,))
    conn.commit()
    return updated


def assemble(conn, document_id: str, revision: int) -> dict:
    state = _current(conn, document_id, revision)
    sections = state["plan"]["sections"]
    if not state["plan"]["outline_confirmed"]:
        raise ValidationFailed("请先确认当前大纲再组装")
    for section in sections:
        _section_context(state, section["id"])
    if not sections or any(not item["content_md"].strip() for item in sections):
        raise ValidationFailed("请先完成每一节正文，再组装母稿")
    return {"content_md": "\n\n".join(f"## {item['title']}\n\n{item['content_md']}" for item in sections)}


def review_document(
    conn, document_id: str, *, content_md: str | None = None, title: str | None = None
) -> dict:
    doc = get_document(conn, document_id)
    if content_md is not None:
        doc = {**doc, "content_md": content_md}
    if title is not None:
        doc = {**doc, "title": title}
    state = get_workspace(conn, document_id)
    if not doc["content_md"].strip() or len(doc["content_md"]) > 40000:
        raise ValidationFailed("审稿需要正文，单次最多 40000 字符；长稿请分篇审核")
    if any(item["stale"] for item in state["excerpts"]):
        raise ValidationFailed("证据已变化，请先核对摘录再审稿")
    if sum(len(item["quote"]) for item in state["excerpts"]) > 30000:
        raise ValidationFailed("审稿摘录超过 30000 字符，请精简证据")
    context = {
        "plan": state["plan"],
        "evidence": state["excerpts"],
        "title": doc["title"],
        "content_md": doc["content_md"],
    }
    # Outline prose is not needed for reviewing the assembled manuscript.
    context["plan"] = {key: value for key, value in state["plan"].items() if key != "sections"}
    result = _proposal(
        conn,
        doc,
        "studio_review",
        context,
        '审稿：检查论证跳跃、事实与推断混淆、来源缺口、反方、重复、标题夸大。不要重写全文。每个问题的quote必须逐字取自正文，suggestion提供可编辑的替代文字，不新增事实。返回 JSON {"issues":[{"quote":"原段落","reason":"问题","suggestion":"建议替换文字"}]}。',
    )
    issues = result["output"].get("issues")
    if not isinstance(issues, list):
        raise ValidationFailed("模型未返回有效审稿结果")
    accepted = []
    for issue in issues[:15]:
        if (
            not isinstance(issue, dict)
            or not all(isinstance(issue.get(key), str) for key in ("quote", "reason", "suggestion"))
            or not issue["quote"].strip()
            or issue["quote"] not in doc["content_md"]
        ):
            raise ValidationFailed("审稿结果未准确定位到原文，请重试")
        accepted.append(issue)
    result["output"] = {"issues": accepted}
    result["body_hash"] = _hash(doc["content_md"])
    return _record(conn, document_id, "review", result)
