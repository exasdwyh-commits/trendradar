"""Model provider abstraction.

Slots (env): FAST_MODEL (cheap: classify / label / insights / story assessment), ANALYSIS_MODEL (reasoning:
cluster analysis, opportunity generation, Ask; also writing unless WRITING_MODEL is set), WRITING_MODEL
(optional: 写作台 drafting / rewriting). Any OpenAI-compatible chat/completions endpoint works.

Providers:
  OpenAICompatibleLLM  real calls with bounded retry, ai_runs telemetry and 24h budget enforcement
  FixtureLLM           pre-authored responses for the bundled demo scenarios (demo seed + tests)

Nothing in the pipeline imports httpx for models directly — everything goes through `chat_json`.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any, Protocol

import httpx

from ..core.errors import BudgetExceeded, NotConfigured
from ..core.logging import get_logger
from ..core.settings import model_environment

log = get_logger("llm")

SLOTS = ("FAST_MODEL", "ANALYSIS_MODEL", "WRITING_MODEL")


@dataclass(frozen=True)
class Slot:
    name: str
    base_url: str
    api_key: str
    model: str
    input_cny_per_million: float = 0.0
    output_cny_per_million: float = 0.0
    rolling_24h_call_limit: int = 0

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)


def load_slot(name: str) -> Slot:
    prefix = name.upper()
    env = model_environment()
    return Slot(
        name=name,
        base_url=(env.get(f"{prefix}_BASE_URL") or env.get("MODEL_BASE_URL", "")).rstrip("/"),
        api_key=env.get(f"{prefix}_API_KEY") or env.get("MODEL_API_KEY", ""),
        model=env.get(f"{prefix}_MODEL", ""),
        input_cny_per_million=float(env.get(f"{prefix}_INPUT_CNY_PER_M", "0") or 0),
        output_cny_per_million=float(env.get(f"{prefix}_OUTPUT_CNY_PER_M", "0") or 0),
        rolling_24h_call_limit=int(env.get(f"{prefix}_24H_CALL_LIMIT", "0") or 0),
    )


def slot_status() -> dict[str, dict]:
    out = {}
    for name in SLOTS:
        slot = load_slot(name)
        out[name] = {
            "enabled": slot.enabled,
            "model": slot.model or None,
            "call_limit_24h": slot.rolling_24h_call_limit or None,
        }
    return out


# ───────────────────────── telemetry & budget ─────────────────────────


def _estimate_cost(slot: Slot, input_tokens: int, output_tokens: int) -> float:
    return round(
        input_tokens / 1e6 * slot.input_cny_per_million + output_tokens / 1e6 * slot.output_cny_per_million, 6
    )


def rolling_24h_usage(conn: sqlite3.Connection | None, slot_name: str | None = None) -> dict:
    if conn is None:
        return {"calls": 0, "cost": 0.0, "input_tokens": 0, "output_tokens": 0}
    where = "run_at >= datetime('now','-24 hours')"
    params: tuple = ()
    if slot_name:
        where += " AND slot=?"
        params = (slot_name,)
    row = conn.execute(
        f"SELECT COUNT(*) calls, COALESCE(SUM(cost),0) cost, COALESCE(SUM(input_tokens),0) i, COALESCE(SUM(output_tokens),0) o FROM ai_runs WHERE {where} AND ok=1",
        params,
    ).fetchone()
    return {
        "calls": int(row["calls"]),
        "cost": float(row["cost"]),
        "input_tokens": int(row["i"]),
        "output_tokens": int(row["o"]),
    }


def _enforce_budget(conn: sqlite3.Connection | None, slot: Slot) -> None:
    if conn is None:
        return
    if slot.rolling_24h_call_limit > 0:
        usage = rolling_24h_usage(conn, slot.name)
        if usage["calls"] >= slot.rolling_24h_call_limit:
            raise BudgetExceeded(
                f"{slot.name} rolling 24h call limit reached: {usage['calls']}/{slot.rolling_24h_call_limit}"
            )
    budget = float(model_environment().get("AI_24H_BUDGET_CNY", "0") or 0)
    if budget > 0:
        usage = rolling_24h_usage(conn)
        if usage["cost"] >= budget:
            raise BudgetExceeded(f"AI rolling 24h budget reached: ¥{usage['cost']:.4f}/¥{budget:.4f}")


def log_ai_run(conn: sqlite3.Connection | None, **fields: Any) -> None:
    if conn is None:
        return
    try:
        conn.execute(
            """INSERT INTO ai_runs(task,slot,model,input_tokens,output_tokens,cost,duration_ms,ok,error,attempts,retries,http_status,job_id)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                fields.get("task"),
                fields.get("slot"),
                fields.get("model"),
                int(fields.get("input_tokens", 0)),
                int(fields.get("output_tokens", 0)),
                float(fields.get("cost", 0.0)),
                int(fields.get("duration_ms", 0)),
                1 if fields.get("ok") else 0,
                (fields.get("error") or None) and str(fields.get("error"))[:1000],
                int(fields.get("attempts", 1)),
                int(fields.get("retries", 0)),
                fields.get("http_status"),
                fields.get("job_id"),
            ),
        )
        conn.commit()
    except sqlite3.Error:  # observability must never break the product path
        pass


def json_from_text(text: str) -> Any:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def _retry_after(response: httpx.Response | None, attempt: int) -> float:
    if response is not None and response.headers.get("Retry-After"):
        value = response.headers["Retry-After"]
        try:
            return max(0.0, min(30.0, float(value)))
        except ValueError:
            try:
                return max(0.0, min(30.0, parsedate_to_datetime(value).timestamp() - time.time()))
            except (TypeError, ValueError, OverflowError):
                pass
    return min(8.0, float(2 ** max(0, attempt - 1)))


# ───────────────────────── providers ─────────────────────────


class LLMProvider(Protocol):
    name: str

    def slot_enabled(self, slot: str) -> bool: ...

    def chat_json(
        self,
        slot: str,
        system: str,
        user: str,
        *,
        task: str,
        conn: sqlite3.Connection | None = None,
        timeout: float = 90,
        job_id: str | None = None,
    ) -> tuple[Any, str]: ...


class OpenAICompatibleLLM:
    name = "openai_compatible"

    def slot_enabled(self, slot: str) -> bool:
        return load_slot(slot).enabled

    def chat_json(
        self,
        slot_name: str,
        system: str,
        user: str,
        *,
        task: str,
        conn=None,
        timeout: float = 90,
        job_id: str | None = None,
        max_attempts: int = 3,
    ) -> tuple[Any, str]:
        slot = load_slot(slot_name)
        if not slot.enabled:
            log_ai_run(
                conn,
                task=task,
                slot=slot_name,
                model=None,
                ok=False,
                error="slot not configured",
                attempts=0,
                job_id=job_id,
            )
            raise NotConfigured(f"model slot not configured: {slot_name}")
        try:
            _enforce_budget(conn, slot)
        except BudgetExceeded as exc:
            log_ai_run(
                conn,
                task=task,
                slot=slot_name,
                model=slot.model,
                ok=False,
                error=str(exc),
                attempts=0,
                job_id=job_id,
            )
            raise
        url = (
            slot.base_url
            if slot.base_url.endswith("/chat/completions")
            else slot.base_url + "/chat/completions"
        )
        payload: dict[str, Any] = {
            "model": slot.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        headers = {"Authorization": f"Bearer {slot.api_key}", "Content-Type": "application/json"}
        started = time.perf_counter()
        last_error: str = ""
        last_status: int | None = None
        attempts = retries = 0
        with httpx.Client(timeout=timeout) as client:
            for attempt in range(1, max_attempts + 1):
                attempts = attempt
                response: httpx.Response | None = None
                try:
                    response = client.post(url, headers=headers, json=payload)
                    last_status = response.status_code
                    if response.status_code == 400 and "response_format" in payload:
                        payload.pop("response_format", None)  # some gateways reject it
                        response = client.post(url, headers=headers, json=payload)
                        last_status = response.status_code
                    if response.status_code == 429 or response.status_code >= 500:
                        raise httpx.HTTPStatusError(
                            f"transient HTTP {response.status_code}",
                            request=response.request,
                            response=response,
                        )
                    response.raise_for_status()
                    data = response.json()
                    text = data["choices"][0]["message"]["content"]
                    parsed = json_from_text(text)
                    usage = data.get("usage") or {}
                    it = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
                    ot = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
                    log_ai_run(
                        conn,
                        task=task,
                        slot=slot_name,
                        model=slot.model,
                        input_tokens=it,
                        output_tokens=ot,
                        cost=_estimate_cost(slot, it, ot),
                        duration_ms=int((time.perf_counter() - started) * 1000),
                        ok=True,
                        attempts=attempts,
                        retries=retries,
                        http_status=last_status,
                        job_id=job_id,
                    )
                    return parsed, slot.model
                except (
                    httpx.TransportError,
                    httpx.HTTPStatusError,
                    json.JSONDecodeError,
                    KeyError,
                    TypeError,
                ) as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                    transient = (
                        isinstance(exc, (httpx.TransportError, json.JSONDecodeError, KeyError, TypeError))
                        or last_status == 429
                        or (last_status or 0) >= 500
                    )
                    if not transient or attempt >= max_attempts:
                        break
                    retries += 1
                    time.sleep(_retry_after(response, attempt))
        log_ai_run(
            conn,
            task=task,
            slot=slot_name,
            model=slot.model,
            duration_ms=int((time.perf_counter() - started) * 1000),
            ok=False,
            error=last_error,
            attempts=attempts,
            retries=retries,
            http_status=last_status,
            job_id=job_id,
        )
        raise RuntimeError(
            f"{task} failed after {attempts} attempt(s)"
            + (f" (HTTP {last_status})" if last_status else "")
            + f": {last_error}"
        )


class FixtureLLM:
    """Deterministic provider backed by sources/mock/fixtures/analysis_fixtures.json.

    Resolves the demo case from the external ids present in the request payload, then returns the
    pre-authored analysis with internal ids substituted. Unknown items fall back to rule-ish defaults.
    """

    name = "fixture"

    def __init__(self, fixtures: dict | None = None):
        if fixtures is None:
            from ..sources.mock import load_analysis_fixtures

            fixtures = load_analysis_fixtures()
        self.cases: dict[str, dict] = fixtures["cases"]
        self.product_insights: dict[str, dict] = fixtures.get("product_insights", {})
        self.stories: dict[str, dict] = fixtures.get("stories", {})
        self._signal_case = {
            sid: case for case, data in self.cases.items() for sid in data["signal_external_ids"]
        }
        self._product_case = {
            pid: case for case, data in self.cases.items() for pid in data.get("product_external_ids", [])
        }
        self.calls: list[str] = []

    def slot_enabled(self, slot: str) -> bool:
        return True

    def _case_for(self, external_ids: list[str]) -> str | None:
        counts: dict[str, int] = {}
        for ext in external_ids:
            case = self._signal_case.get(ext) or self._product_case.get(ext)
            if case:
                counts[case] = counts.get(case, 0) + 1
        if not counts:
            return None
        best = max(counts.items(), key=lambda kv: kv[1])
        return best[0] if best[1] >= max(1, len(external_ids) // 3) else None

    def chat_json(
        self,
        slot: str,
        system: str,
        user: str,
        *,
        task: str,
        conn=None,
        timeout: float = 90,
        job_id: str | None = None,
    ) -> tuple[Any, str]:
        self.calls.append(task)
        payload = json.loads(user) if user.strip().startswith("{") else {}
        handler = getattr(self, f"_task_{task}", None)
        result = handler(payload) if handler else {}
        log_ai_run(conn, task=task, slot=slot, model="fixture", ok=True, job_id=job_id)
        return result, "fixture"

    # ── task handlers ──
    def _task_classify_signals(self, payload: dict) -> dict:
        items = []
        for s in payload.get("signals", []):
            case = self._signal_case.get(s.get("external_id", ""))
            if case:
                data = self.cases[case]
                items.append(
                    {
                        "id": s["id"],
                        "is_pain": True,
                        "relevance": 88,
                        "persona": data["persona"],
                        "category": data["category"],
                        "confidence": 0.9,
                        "reason": "fixture: matches demo scenario",
                    }
                )
            else:
                score = float(s.get("rule_score") or 0)
                items.append(
                    {
                        "id": s["id"],
                        "is_pain": score >= 0.35,
                        "relevance": round(min(100, score * 100)),
                        "persona": None,
                        "category": None,
                        "confidence": 0.4,
                        "reason": "fixture: rule fallback",
                    }
                )
        return {"items": items}

    def _task_label_clusters(self, payload: dict) -> dict:
        items = []
        for c in payload.get("clusters", []):
            case = self._case_for([s.get("external_id", "") for s in c.get("signals", [])])
            if case:
                items.append(
                    {
                        "cluster_id": c["id"],
                        "label": self.cases[case]["label"],
                        "summary": self.cases[case]["summary"],
                        "persona": self.cases[case]["persona"],
                        "category": self.cases[case]["category"],
                    }
                )
            else:
                titles = [s.get("title", "") for s in c.get("signals", [])][:1]
                items.append(
                    {
                        "cluster_id": c["id"],
                        "label": titles[0] if titles else "Untitled cluster",
                        "summary": None,
                        "persona": None,
                        "category": None,
                    }
                )
        return {"items": items}

    def _task_product_insights(self, payload: dict) -> dict:
        items = []
        for p in payload.get("products", []):
            data = self.product_insights.get(p.get("external_id", ""))
            if data:
                items.append({"product_id": p["id"], **data, "confidence": 0.8})
        return {"items": items}

    def _task_analyze_cluster(self, payload: dict) -> dict:
        signals = payload.get("signals", [])
        competitors = payload.get("competitors", [])
        case = self._case_for([s.get("external_id", "") for s in signals])
        if not case:
            return {"error": "no fixture for this cluster"}
        data = self.cases[case]
        ext_to_id = {s.get("external_id"): s["id"] for s in signals}
        ext_to_id.update({p.get("external_id"): p["id"] for p in competitors})
        pains = []
        for ext, ps in data["pain_signals"].items():
            if ext in ext_to_id:
                pains.append({"signal_id": ext_to_id[ext], **ps})
        scores = {}
        for dim, s in data["model_scores"].items():
            scores[dim] = {
                "score": s["score"],
                "reason": s["reason"],
                "evidence_ids": [ext_to_id[e] for e in s["evidence"] if e in ext_to_id],
            }
        return {
            "label": data["label"],
            "summary": data["summary"],
            "persona": data["persona"],
            "category": data["category"],
            "pain_signals": pains,
            "opportunity": data["opportunity"],
            "scores": scores,
        }

    def _task_builder_brief(self, payload: dict) -> dict:
        case = self._case_for(payload.get("evidence_external_ids", []))
        if not case:
            return {"error": "no fixture"}
        return dict(self.cases[case]["builder_brief"])

    def _task_ask_plan(self, payload: dict) -> dict:
        q = (payload.get("question") or "").lower()
        plan: dict[str, Any] = {"min_score": 0, "limit": 5, "sort": "opportunity_score"}
        if "weekend" in q or "two days" in q or "2 days" in q or "quick" in q:
            plan["build_difficulty"] = ["weekend", "2_weeks"]
        if "coding" in q or "developer" in q:
            plan["category"] = "developer_tools"
        if "mac" in q:
            plan["build_type"] = ["mac"]
        return plan

    def _task_ask_answer(self, payload: dict) -> dict:
        opps = payload.get("opportunities", [])
        if not opps:
            return {"answer_md": "No opportunities in the database match this question yet.", "citations": []}
        lines = [
            f"- **{o['title']}** (score {round(o.get('opportunity_score', 0))}) — {o.get('core_pain', '')} [opp:{o['id']}]"
            for o in opps
        ]
        return {
            "answer_md": "Based on stored evidence:\n" + "\n".join(lines),
            "citations": [o["id"] for o in opps],
        }

    def _task_explore_overview(self, payload: dict) -> dict:
        return {
            "overview": f"Market map for '{payload.get('query', '')}' built from {payload.get('signal_count', 0)} signals and {payload.get('product_count', 0)} products (fixture summary)."
        }

    # ── studio (creator) tasks: template output from the demo materials, clearly labelled by the caller ──
    def _task_assess_stories(self, payload: dict) -> dict:
        stories = self.stories
        items = []
        for it in payload.get("items", []):
            fx = stories.get(str(it.get("external_id", "")))
            if fx:
                items.append({"id": it["id"], **fx})
        return {"items": items}

    @staticmethod
    def _ctx(payload: dict) -> dict:
        return payload.get("context") or {}

    def _task_studio_angles(self, payload: dict) -> dict:
        ctx = self._ctx(payload)
        mats = ctx.get("materials") or []
        thesis = ctx.get("thesis") or (mats[0]["title"] if mats else ctx.get("title", ""))
        angles = [
            {
                "title": f"{thesis[:24]}：机制比结论重要",
                "angle": "先解释为什么会发生，再判断会不会持续。",
                "why_now": "素材是近期第一方信息。",
                "risk": "样本只有一家公司。",
            },
            {
                "title": "谁在为这个变化买单",
                "angle": "沿着利润和成本的流向找真正的赢家和输家。",
                "why_now": "价格/成本结构刚刚改变。",
                "risk": "缺少对手方数据。",
            },
            {
                "title": "对中国同行意味着什么",
                "angle": "把海外案例映射到国内企业的采购、定价与组织。",
                "why_now": "国内尚无同类公开案例。",
                "risk": "映射可能过度类比。",
            },
        ]
        return {"angles": angles}

    def _task_studio_agent_plan(self, payload: dict) -> dict:
        plan = payload.get("plan") or {}
        excerpts = []
        for index, material in enumerate((payload.get("materials") or [])[:3]):
            quote = (material.get("content") or material.get("summary") or material.get("quote") or "")[
                :500
            ].strip()
            if quote:
                excerpts.append(
                    {
                        "id": f"demo-{index}",
                        "material_id": material["id"],
                        "fact": "演示：已提供素材中的原文",
                        "quote": quote,
                        "stance": "context",
                    }
                )
        evidence_ids = [e["id"] for e in payload.get("evidence", [])] + [e["id"] for e in excerpts]
        return {
            "title": payload.get("title") or "演示母稿",
            "audience": plan.get("audience") or "关注商业机制的公众号读者",
            "question": plan.get("question") or "这个变化背后的机制是什么？",
            "proposition": plan.get("proposition") or "【待补充：作者确认核心判断】",
            "gaps": ["演示模板：请核对来源、补充机制证据和反方；这不是事实核验。"],
            "excerpts": excerpts,
            "sections": [
                {"title": title, "goal": goal, "target_words": 400, "evidence_ids": evidence_ids}
                for title, goal in (
                    ("发生了什么", "区分素材事实与作者判断"),
                    ("机制与证据", "用证据展开机制"),
                    ("反方与边界", "说明判断的适用范围"),
                )
            ],
        }

    def _task_studio_section(self, payload: dict) -> dict:
        evidence = payload.get("evidence") or []
        parts = []
        for item in evidence:
            source = (
                f"[来源]({item['source_url']})"
                if item.get("source_url")
                else item.get("source_title", "资料")
            )
            parts.append(f"{item['quote']}（{source}）")
        parts.append("【待补充：结合上述证据完成本节论证。演示模板不代表模型写作质量。】")
        return {"content_md": "\n\n".join(parts)}

    def _task_studio_review(self, payload: dict) -> dict:
        body = payload.get("content_md") or ""
        marker = "【待补充"
        if marker not in body:
            return {"issues": []}
        line = next(line for line in body.splitlines() if marker in line)
        return {
            "issues": [
                {"quote": line, "reason": "演示检查：这里仍有未完成的论证，请人工补充。", "suggestion": line}
            ]
        }

    def _task_studio_outline(self, payload: dict) -> dict:
        ctx = self._ctx(payload)
        mats = ctx.get("materials") or []
        src = mats[0]["title"] if mats else "素材"
        outline = "\n".join(
            [
                "## 一个反直觉的开头",
                f"- 用「{src}」中最意外的事实切入",
                "- 交代读者为什么该在意",
                "## 发生了什么",
                "- 按素材复述关键事实与数字（标注来源）",
                "- 区分事实、公司说法与推测",
                "## 为什么会发生：机制",
                "- 成本结构 / 定价 / 渠道 / 组织中哪一项变了",
                "- 谁的利润在迁移",
                "## 反方",
                "- 这个判断最可能错在哪里",
                "- 需要什么数据才能确认（【待补充】）",
                "## 中国映射",
                "- 国内哪些企业面临同样的选择",
                "## 结论",
                "- 一句话判断 + 一个可观察的信号",
            ]
        )
        return {
            "thesis": ctx.get("thesis") or f"{src}背后是利润池的迁移，而不是一次性的价格变化。",
            "outline_md": outline,
        }

    def _task_studio_draft(self, payload: dict) -> dict:
        ctx = self._ctx(payload)
        mats = ctx.get("materials") or []
        parts = [f"# {ctx.get('title') or '未命名'}", ""]
        if ctx.get("thesis"):
            parts += [f"**核心判断：{ctx['thesis']}**", ""]
        parts += ["## 发生了什么", ""]
        for m in mats:
            parts += [
                f"{m.get('summary') or m.get('quote') or m.get('title')}（来源：{m.get('source') or m.get('title')}）",
                "",
            ]
        parts += [
            "## 为什么会发生",
            "",
            "【待补充：结合素材解释成本结构、定价或渠道中发生变化的那一项，以及谁的利润在迁移。】",
            "",
            "## 反方",
            "",
            "【待补充：这个判断最可能错在哪里？需要哪条数据才能确认？】",
            "",
            "## 中国映射",
            "",
            "【待补充：国内哪些企业面临同样的选择，它们的约束条件有什么不同。】",
            "",
            "（演示初稿：未配置写作模型时由模板生成，仅用于展示流程。）",
        ]
        return {"title": ctx.get("title") or "未命名", "content_md": "\n".join(parts)}

    def _task_studio_titles(self, payload: dict) -> dict:
        ctx = self._ctx(payload)
        base = (ctx.get("thesis") or ctx.get("title") or "这个变化")[:28]
        return {
            "titles": [
                {"title": base, "subtitle": "一个被低估的机制变化", "style": "判断"},
                {"title": f"为什么{base[:16]}会发生？", "subtitle": "", "style": "问题"},
                {"title": f"{base[:20]}：谁在买单", "subtitle": "", "style": "判断"},
                {"title": f"{base[:20]}之后，还会发生什么", "subtitle": "", "style": "问题"},
                {"title": f"看懂{base[:16]}的三个数字", "subtitle": "", "style": "数字"},
                {"title": f"{base[:18]}不是好消息", "subtitle": "至少对一部分人不是", "style": "反直觉"},
            ]
        }

    def _task_studio_rewrite(self, payload: dict) -> dict:
        sel = payload.get("selection") or ""
        mode = payload.get("mode")
        if mode == "concise":
            sentences = [x for x in sel.replace("。", "。\n").splitlines() if x.strip()]
            return {"text": "".join(sentences[: max(1, int(len(sentences) * 0.7))])}
        if mode == "english":
            return {"text": "[EN] " + sel}
        return {"text": sel}

    def _task_studio_variant(self, payload: dict) -> dict:
        ctx = self._ctx(payload)
        platform = payload.get("platform") or "xiaohongshu"
        body = ctx.get("content_md") or ""
        lines = [x.strip("#> ").strip() for x in body.splitlines() if x.strip() and not x.startswith("（")]
        points = [x for x in lines if len(x) > 8][:7]
        title = ctx.get("title") or "未命名"
        if platform == "xiaohongshu":
            md = (
                f"**{title[:20]}**\n\n"
                + "\n".join(f"{i + 1}. {p[:60]}" for i, p in enumerate(points))
                + "\n\n你怎么看？评论区聊聊。"
            )
            return {
                "title": title[:20],
                "content_md": md,
                "meta": {"tags": ["商业观察", "AI商业化", "行业分析", "创业", "案例拆解"]},
            }
        if platform == "x":
            md = "\n\n".join(f"{i + 1}/ {p[:200]}" for i, p in enumerate(points))
            return {"title": title, "content_md": md, "meta": {"tags": []}}
        return {
            "title": (f"为什么{title}" if platform == "zhihu" else title),
            "content_md": body,
            "meta": {"tags": []},
        }


# ───────────────────────── resolution ─────────────────────────

_override: LLMProvider | None = None
_default = OpenAICompatibleLLM()


def set_llm(provider: LLMProvider | None) -> None:
    """Install a provider override (tests, demo seed). Pass None to restore the real provider."""
    global _override
    _override = provider


def get_llm() -> LLMProvider:
    return _override or _default


def fixture_llm() -> FixtureLLM:
    return FixtureLLM()


def resolve_llm(slot: str, data_mode: str) -> LLMProvider | None:
    """Pick the provider for a piece of work.

    Real model if configured; otherwise the fixture provider — but only for mock data. Live data is
    never analysed with canned answers: the caller must skip and record 'not configured'.
    """
    provider = get_llm()
    if provider.slot_enabled(slot):
        return provider
    if data_mode == "mock":
        return fixture_llm()
    return None
