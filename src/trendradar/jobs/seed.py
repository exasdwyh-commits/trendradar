"""Demo seed: run the whole pipeline on mock adapters with the fixture analysis provider.

Produces the three preset demo cases end-to-end (Pain → Competition → Gap → Opportunity) without any
API key, deterministically and for free. Everything it writes is labelled origin='mock' / data_mode='mock'.
"""

from __future__ import annotations

import sqlite3

from ..core.config import get_pipeline_config, sources_path
from ..providers.llm import FixtureLLM, get_llm, set_llm
from ..sources.registry import build_adapters, load_source_configs, sync_sources
from .pipeline import run_daily


def seed_demo(conn: sqlite3.Connection) -> dict:
    configs = load_source_configs(sources_path())
    all_adapters = build_adapters(configs)
    adapters = [a for a in all_adapters if a.mode == "mock"]
    sync_sources(conn, configs, all_adapters)
    previous = get_llm()
    set_llm(FixtureLLM())
    try:
        result = run_daily(
            conn, adapters=adapters, cfg=get_pipeline_config(), job_type="seed", force_analyze=True
        )
        _seed_demo_document(conn)
        return result
    finally:
        set_llm(None if getattr(previous, "name", "") == "openai_compatible" else previous)


DEMO_DOC_TITLE = "（演示）按结果计费会不会成为 AI 服务的默认定价方式？"


def _seed_demo_document(conn: sqlite3.Connection) -> None:
    """One demo piece so the studio is not empty; built only from demo materials (data_mode='mock')."""
    from ..studio.documents import create_document
    from ..studio.materials import material_from_signal

    if conn.execute("SELECT 1 FROM documents WHERE title=?", (DEMO_DOC_TITLE,)).fetchone():
        return
    row = conn.execute(
        "SELECT id FROM signals WHERE source_id='mock-stories' AND external_id='st-01'"
    ).fetchone()
    if not row:
        return
    material_id = material_from_signal(conn, row["id"])
    body = "\n".join(
        [
            "> 核心判断：当计费单位从 token 变成结果，模型厂商的收入将更依赖任务成功率而非调用量。",
            "",
            "## 发生了什么",
            "",
            "Northwind Cloud 把旗舰推理 API 价格下调 45%，同时推出按成功任务数付费的 Outcome Plan（来源：Northwind Cloud 官方博客）。",
            "",
            "## 为什么会发生",
            "",
            "【待补充：自研芯片与调度效率如何支撑 55% 以上的毛利率——需要素材中的成本拆分。】",
            "",
            "## 反方",
            "",
            "如果任务成功率由客户的数据质量决定，按结果计费就把风险转移给了模型厂商。",
            "",
            "（演示稿件：由虚构素材生成，仅用于展示编辑器与 AI 助手流程。）",
        ]
    )
    create_document(
        conn,
        title=DEMO_DOC_TITLE,
        content_md=body,
        thesis="当计费单位从 token 变成结果，模型厂商的收入将更依赖任务成功率而非调用量。",
        lane="AI_COMMERCIALIZATION",
        seed_material_id=material_id,
        status="draft",
        meta={"demo": True},
    )
