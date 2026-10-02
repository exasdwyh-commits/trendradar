"""Durable editorial agent: one model/tool step per request, with human checkpoints.

The editor drives successive requests while its Agent panel is active. Each completed step
is persisted; leaving the panel stops further steps, not the in-flight operation. A lease
prevents two tabs from paying for the same step. Candidates never alter the manuscript
until explicit adoption, which snapshots and saves the complete result atomically.
"""

from __future__ import annotations

import copy
import json
import time

from ..core.errors import NotFound, RadarError, ValidationFailed
from ..core.ids import new_id
from . import ai, creation, documents

PHASES = {"planning", "drafting", "reviewing", "variants"}
LEASE_SECONDS = 900  # Covers the provider's bounded HTTP retries, without holding a DB transaction.


def _decode(row) -> dict:
    result = dict(row)
    result["state"] = json.loads(result.pop("state_json"))
    result["running"] = result.pop("lease_until") > time.time()
    result.pop("lease_token")
    return result


def get_latest(conn, did: str) -> dict | None:
    if not conn.execute("SELECT 1 FROM documents WHERE id=?", (did,)).fetchone():
        raise NotFound("稿件不存在")
    row = conn.execute(
        "SELECT * FROM writing_agent_runs WHERE document_id=? ORDER BY rowid DESC LIMIT 1", (did,)
    ).fetchone()
    return _decode(row) if row else None


def _load(conn, did: str, rid: str, revision: int) -> dict:
    run = get_latest(conn, did)
    if not run or run["id"] != rid:
        raise NotFound("创作 Agent 任务不存在或已被新任务替代")
    if run["revision"] != revision:
        raise ValidationFailed("Agent 进度已更新，请刷新进度后继续")
    return run


def _fingerprint(conn, did: str) -> str:
    doc = documents.get_document(conn, did)
    workspace = creation.get_workspace(conn, did)
    return creation._hash(
        {
            "document": {
                key: doc[key] for key in ("title", "content_md", "thesis", "target_platform", "data_mode")
            },
            "materials": sorted((m["id"], creation._material_hash(m)) for m in doc["materials"]),
            "plan": workspace["plan"],
            "revision": workspace["revision"],
            "excerpts": workspace["excerpts"],
        }
    )


def _guard(conn, did: str, run: dict) -> None:
    if _fingerprint(conn, did) != run["state"]["source_hash"]:
        raise ValidationFailed("正文、规划或素材已变化。请保留当前修改，重新规划 Agent；旧候选稿仍可查看。")


def _persist(conn, run: dict, *, token: str | None = None, commit: bool = True) -> dict:
    cur = conn.execute(
        "UPDATE writing_agent_runs SET status=?,state_json=?,revision=revision+1,lease_token=NULL,lease_until=0,"
        "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=? AND revision=? AND lease_token IS ?",
        (run["status"], json.dumps(run["state"], ensure_ascii=False), run["id"], run["revision"], token),
    )
    if cur.rowcount != 1:
        raise ValidationFailed("Agent 进度已更新，请刷新；本次结果未覆盖新进度")
    if commit:
        conn.commit()
    result = get_latest(conn, run["document_id"])
    assert result is not None
    return result


def start(conn, did: str, instruction: str, platforms: list[str], *, restart: bool = False) -> dict:
    if not isinstance(instruction, str) or len(instruction) > 2000:
        raise ValidationFailed("创作要求最多 2000 字符")
    if not isinstance(platforms, list) or any(p not in ai.PLATFORM_RULES for p in platforms):
        raise ValidationFailed("请选择有效的平台")
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        previous = get_latest(conn, did)
        if previous:
            if not restart:
                return previous
            if previous["running"]:
                raise ValidationFailed("当前步骤仍在执行，请完成后再重新规划")
        state = {
            "instruction": instruction.strip(),
            "platforms": list(dict.fromkeys(platforms)),
            "source_hash": _fingerprint(conn, did),
            "phase": "planning",
            "proposal": None,
            "drafts": [],
            "draft_md": "",
            "review": None,
            "variants": [],
            "error": "",
            "warnings": [],
        }
        conn.execute(
            "INSERT INTO writing_agent_runs(id,document_id,status,state_json) VALUES(?,?,'planning',?)",
            (new_id(), did, json.dumps(state, ensure_ascii=False)),
        )
    result = get_latest(conn, did)
    assert result is not None
    return result


def _text(value, name: str, limit: int, *, required: bool = False) -> str:
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValidationFailed(f"Agent 返回的{name}无效，请修改要求后重新规划")
    return value.strip()


def _validate_proposal(conn, did: str, raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValidationFailed("Agent 未返回有效规划")
    doc = documents.get_document(conn, did)
    workspace = creation.get_workspace(conn, did)
    material_map = {m["id"]: m for m in doc["materials"]}
    known = {item["id"] for item in workspace["excerpts"] if not item["stale"]}
    proposal: dict = {
        key: _text(raw.get(key, ""), key, limit)
        for key, limit in (("title", 200), ("audience", 2000), ("question", 2000), ("proposition", 2000))
    }
    gaps = raw.get("gaps", [])
    excerpts = raw.get("excerpts", [])
    sections = raw.get("sections", [])
    if not isinstance(gaps, list) or len(gaps) > 12 or not isinstance(excerpts, list) or len(excerpts) > 12:
        raise ValidationFailed("Agent 缺口或摘录数量超限")
    if not isinstance(sections, list) or not 1 <= len(sections) <= 8:
        raise ValidationFailed("Agent 大纲需要 1–8 节")
    proposal["gaps"] = [_text(gap, "资料缺口", 1000, required=True) for gap in gaps]
    proposal["excerpts"] = []
    for entry in excerpts:
        if not isinstance(entry, dict):
            raise ValidationFailed("Agent 摘录格式无效")
        eid = _text(entry.get("id"), "摘录 ID", 100, required=True)
        material = (
            material_map.get(entry.get("material_id")) if isinstance(entry.get("material_id"), str) else None
        )
        quote = _text(entry.get("quote"), "摘录", 6000, required=True)
        if (
            eid in known
            or not material
            or not any(quote in (material.get(k) or "") for k in ("content", "summary", "quote"))
        ):
            raise ValidationFailed("Agent 摘录必须逐字来自已绑定素材，且 ID 不能重复")
        known.add(eid)
        stance = entry.get("stance", "support")
        if stance not in ("support", "counter", "context"):
            raise ValidationFailed("Agent 摘录立场无效")
        proposal["excerpts"].append(
            {
                "id": eid,
                "material_id": material["id"],
                "source_title": material["title"],
                "fact": _text(entry.get("fact"), "事实说明", 1000, required=True),
                "quote": quote,
                "stance": stance,
            }
        )
    if sum(len(e["quote"]) for e in proposal["excerpts"] + workspace["excerpts"]) > 30000:
        raise ValidationFailed("摘录超过 30000 字符，请减少资料后重新规划")
    proposal["sections"] = []
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            raise ValidationFailed("Agent 章节格式无效")
        ids = section.get("evidence_ids", [])
        words = section.get("target_words", 400)
        if not isinstance(ids, list) or not all(isinstance(eid, str) and eid in known for eid in ids):
            raise ValidationFailed("Agent 章节引用了不存在的证据")
        if type(words) is not int or not 50 <= words <= 5000:
            raise ValidationFailed("Agent 章节目标字数需为 50–5000")
        proposal["sections"].append(
            {
                "id": f"agent-{index + 1}",
                "title": _text(section.get("title"), "章节标题", 200, required=True),
                "goal": _text(section.get("goal", ""), "章节目标", 2000),
                "target_words": words,
                "evidence_ids": list(dict.fromkeys(ids)),
                "content_md": "",
            }
        )
    return proposal


def _plan(conn, did: str, run: dict) -> None:
    doc = documents.get_document(conn, did)
    workspace = creation.get_workspace(conn, did)
    if any(e["stale"] for e in workspace["excerpts"]):
        raise ValidationFailed("证据摘录已过期，请先在创作规划中核对")
    context = {
        "plan": workspace["plan"],
        "evidence": workspace["excerpts"],
        "title": doc["title"],
        "content_md": doc["content_md"],
        "author_request": run["state"]["instruction"],
        "materials": []
        if workspace["excerpts"]
        else [
            {key: m.get(key) for key in ("id", "title", "url", "content", "summary", "quote")}
            for m in doc["materials"]
        ],
    }
    result = creation._proposal(
        conn,
        doc,
        "studio_agent_plan",
        context,
        "规划公众号母稿，优先遵循已有规划和作者要求。整理已有依据与缺口，提出1–8节大纲。"
        "引用现有摘录ID；没有摘录时从materials中逐字选择原文，最多12条，总原文不超过30000字符。"
        "缺少资料写入gaps，不得编造或声称已检索。返回JSON："
        '{"title":"候选标题","audience":"读者","question":"问题","proposition":"核心判断",'
        '"gaps":["资料缺口"],"excerpts":[{"id":"e1","material_id":"已绑定素材ID",'
        '"fact":"事实说明","quote":"逐字原文","stance":"support|counter|context"}],'
        '"sections":[{"title":"小标题","goal":"论证目标","target_words":400,"evidence_ids":["e1"]}]}。',
    )
    proposal = _validate_proposal(conn, did, result["output"])
    evidence = workspace["excerpts"] + proposal["excerpts"]
    # Check authored claims, excluding IDs and target word counts. Proposed quotes
    # are safe evidence here because validation already matched them to bound materials.
    claims = [proposal[k] for k in ("title", "question", "proposition")] + proposal["gaps"]
    claims += [e["fact"] for e in proposal["excerpts"]]
    claims += [s[k] for s in proposal["sections"] for k in ("title", "goal")]
    result["warnings"] = ai.number_warnings(
        "\n".join(claims),
        [e["quote"] for e in evidence] + [doc["content_md"], workspace["plan"].get("author_notes", "")],
    )
    if not evidence:
        result["warnings"].append("没有选择证据摘录：事实缺口应标记待补充，请核实后采用。")
    if result["model"] == "fixture":
        result["warnings"].insert(0, "演示模板：本次未调用真实模型，输出仅用于体验流程。")
    creation._record(conn, did, "agent_plan", result)
    run["state"]["proposal"] = proposal
    run["state"]["model"] = result["model"]
    run["state"]["warnings"] = result["warnings"]
    run["status"] = "awaiting_outline"


def advance(conn, did: str, rid: str, revision: int) -> dict:
    run = _load(conn, did, rid, revision)
    if run["status"] not in PHASES | {"failed"}:
        return run
    token = new_id()
    cur = conn.execute(
        "UPDATE writing_agent_runs SET lease_token=?,lease_until=? WHERE id=? AND revision=? AND lease_until<=?",
        (token, time.time() + LEASE_SECONDS, rid, revision, time.time()),
    )
    conn.commit()
    if cur.rowcount != 1:
        raise ValidationFailed("当前步骤仍在执行，请刷新进度；不会重复调用模型")
    previous = copy.deepcopy(run["state"])
    try:
        _guard(conn, did, run)
        state = run["state"]
        phase = state["phase"]
        state["error"] = ""
        if phase == "planning":
            _plan(conn, did, run)
        elif phase == "drafting":
            workspace = creation.get_workspace(conn, did)
            section = workspace["plan"]["sections"][len(state["drafts"])]
            result = creation.generate_section(
                conn, did, section["id"], workspace["revision"], state["instruction"]
            )
            state["drafts"].append({"section_id": section["id"], "title": section["title"], **result})
            if len(state["drafts"]) == len(workspace["plan"]["sections"]):
                state["draft_md"] = "\n\n".join(
                    f"## {d['title']}\n\n{d['output']['content_md']}" for d in state["drafts"]
                )
                state["phase"] = "reviewing"
            run["status"] = state["phase"]
        elif phase == "reviewing":
            state["review"] = creation.review_document(
                conn,
                did,
                content_md=state["draft_md"],
                title=state["proposal"]["title"] or documents.get_document(conn, did)["title"],
            )
            state["phase"] = "variants"
            run["status"] = "variants" if state["platforms"] else "awaiting_adoption"
        elif phase == "variants":
            platform = state["platforms"][len(state["variants"])]
            result = ai.run_action(
                conn,
                did,
                "variant",
                {"platform": platform},
                candidate={
                    "title": state["proposal"]["title"] or documents.get_document(conn, did)["title"],
                    "content_md": state["draft_md"],
                },
            )
            state["variants"].append({"platform": platform, **result})
            run["status"] = (
                "awaiting_adoption" if len(state["variants"]) == len(state["platforms"]) else "variants"
            )
        else:
            raise ValidationFailed("任务阶段无效，请重新规划")
        _guard(conn, did, run)
    except Exception as error:
        conn.rollback()
        run["state"] = previous
        run["state"]["error"] = (
            error.message
            if isinstance(error, RadarError)
            else "当前步骤未完成，原稿与已完成进度已保留。请检查模型服务后重试。"
        )
        run["status"] = "failed"
    return _persist(conn, run, token=token)


def _checkpoint(conn, did: str, rid: str, revision: int, status: str) -> dict:
    run = _load(conn, did, rid, revision)
    if run["running"] or run["status"] != status:
        raise ValidationFailed("请等待当前步骤完成，并刷新后在对应阶段操作")
    _guard(conn, did, run)
    # Expired leases may be reclaimed at a checkpoint, without allowing stale responses to write.
    conn.execute("UPDATE writing_agent_runs SET lease_token=NULL,lease_until=0 WHERE id=?", (rid,))
    return run


def confirm(conn, did: str, rid: str, revision: int, proposal: dict) -> dict:
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        run = _checkpoint(conn, did, rid, revision, "awaiting_outline")
        proposal = _validate_proposal(conn, did, proposal)
        workspace = creation.get_workspace(conn, did)
        doc = documents.get_document(conn, did)
        material_map = {m["id"]: m for m in doc["materials"]}
        remap = {}
        for e in proposal["excerpts"]:
            remap[e["id"]] = new_id()
            m = material_map[e["material_id"]]
            conn.execute(
                "INSERT INTO document_excerpts(id,document_id,material_id,fact,quote,stance,source_hash,source_title,source_url,source_date,origin) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    remap[e["id"]],
                    did,
                    m["id"],
                    e["fact"],
                    e["quote"],
                    e["stance"],
                    creation._material_hash(m),
                    m["title"],
                    m.get("url"),
                    m.get("published_at"),
                    m["origin"],
                ),
            )
        plan = {
            **workspace["plan"],
            **{k: proposal[k] for k in ("audience", "question", "proposition")},
            "gaps": "\n".join(proposal["gaps"]),
            "outline_confirmed": True,
            "sections": [
                {**s, "evidence_ids": [remap.get(eid, eid) for eid in s["evidence_ids"]]}
                for s in proposal["sections"]
            ],
        }
        conn.execute(
            "INSERT INTO document_workspaces(document_id,data_json,revision) VALUES(?,?,?) ON CONFLICT(document_id) DO UPDATE SET data_json=excluded.data_json,revision=excluded.revision,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",
            (did, json.dumps(plan, ensure_ascii=False), workspace["revision"] + 1),
        )
        run["state"]["proposal"] = proposal
        run["state"]["source_hash"] = _fingerprint(conn, did)
        run["state"]["phase"] = run["status"] = "drafting"
        _persist(conn, run, commit=False)
    result = get_latest(conn, did)
    assert result is not None
    return result


def adopt(conn, did: str, rid: str, revision: int) -> dict:
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = _load(conn, did, rid, revision)
        if existing["status"] == "completed":
            return existing
        run = _checkpoint(conn, did, rid, revision, "awaiting_adoption")
        state = run["state"]
        workspace = creation.get_workspace(conn, did)
        doc = documents.get_document(conn, did)
        title = state["proposal"]["title"] or doc["title"]
        documents._snapshot(conn, did, source="ai", note="采用创作 Agent 前的快照")
        conn.execute(
            "UPDATE documents SET title=?,content_md=?,thesis=?,word_count=?,status=CASE WHEN status='idea' THEN 'draft' ELSE status END,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            (
                title,
                state["draft_md"],
                state["proposal"]["proposition"],
                documents.word_count(state["draft_md"]),
                did,
            ),
        )
        drafts = {d["section_id"]: d for d in state["drafts"]}
        plan = {
            **workspace["plan"],
            "sections": [
                {**s, "content_md": drafts[s["id"]]["output"]["content_md"]}
                for s in workspace["plan"]["sections"]
            ],
        }
        conn.execute(
            "UPDATE document_workspaces SET data_json=?,revision=revision+1 WHERE document_id=?",
            (json.dumps(plan, ensure_ascii=False), did),
        )
        source_hash = creation._hash({"title": title, "content_md": state["draft_md"]})
        for variant in state["variants"]:
            out = variant["output"]
            conn.execute(
                "INSERT INTO platform_variants(id,document_id,platform,title,content_md,meta_json,generated_by,warnings_json) VALUES(?,?,?,?,?,?,?,?)",
                (
                    new_id(),
                    did,
                    variant["platform"],
                    out["title"] or title,
                    out["content_md"],
                    json.dumps({**out.get("meta", {}), "source_hash": source_hash}, ensure_ascii=False),
                    variant["generated_by"],
                    json.dumps(variant["warnings"], ensure_ascii=False),
                ),
            )
        for result in state["drafts"] + state["variants"]:
            conn.execute("UPDATE ai_actions SET accepted=1 WHERE id=? AND document_id=?", (result["id"], did))
        run["status"] = "completed"
        _persist(conn, run, commit=False)
    result = get_latest(conn, did)
    assert result is not None
    return result
