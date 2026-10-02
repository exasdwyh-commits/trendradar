"""Editorial assessment of story signals: is this worth writing about, and from which angle?

Story sources (kind='story') bypass the pain classifier. Each new story is scored 0–100 for
"business value worth a piece" with a lane, a one-line why and up to three angles. FAST model when
configured, fixture for demo data, a transparent rule fallback otherwise (labelled as such).
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime

from ..core.timeutil import utcnow
from ..providers.llm import resolve_llm

LANES = ("AI_COMMERCIALIZATION", "INDUSTRY", "COMPANY", "BUSINESS_MODEL", "GLOBALIZATION", "OTHER")
LANE_NAMES = {
    "AI_COMMERCIALIZATION": "AI 商业化",
    "INDUSTRY": "产业与利润池",
    "COMPANY": "公司与战略",
    "BUSINESS_MODEL": "商业模式",
    "GLOBALIZATION": "全球化与中国映射",
    "OTHER": "其他",
}

ASSESS_SYSTEM = """你是一位商业内容主编，为一个只写五类商业内容的公众号选题：
1 公司与战略（财报、资本开支、组织调整、产品战略、并购）
2 产业与利润池（供应链、制造、能源、芯片、机器人、AI 基础设施，重点看利润迁移）
3 商业模式（新产品、新定价、新渠道、一人公司/小团队、AI 原生公司）
4 AI 商业化（不追参数榜，只看真实 ROI、流程替代、成本结构、企业采购）
5 全球化与中国映射（出海、技术授权、海外渠道、跨国供应链，以及对中国企业的映射）

对每条素材判断"值得写的程度"business_value（0-100）：
- 有可验证的商业机制变化（定价、利润、渠道、组织、采购决策）→ 高
- 有具体数字、第一方来源、可以引出反直觉判断 → 加分
- 纯产品发布、娱乐、泛社会话题、没有机制变化的"新闻" → 低（≤30）
lane 取 AI_COMMERCIALIZATION | INDUSTRY | COMPANY | BUSINESS_MODEL | GLOBALIZATION | OTHER。
why：一句话（≤50 字）说明为什么值得写，写出机制而不是复述标题。
angles：0-3 个选题角度，每个 ≤30 字，是可以直接当作文章切口的判断句或问题。
keywords：3-6 个关键词。
只输出 JSON：{"items":[{"id":"...","lane":"...","business_value":0,"why":"...","angles":["..."],"keywords":["..."]}]}"""

_BUSINESS_TERMS = [
    r"财报|营收|利润|毛利|margin|revenue|earnings|guidance|ebitda",
    r"定价|价格|pricing|price cut|subscription|计费|收费",
    r"并购|收购|acqui|merger|融资|ipo|估值|valuation",
    r"裁员|layoff|重组|reorg|关闭|shut down|门店",
    r"供应链|supply chain|产能|capacity|capex|资本开支|工厂|manufactur",
    r"出海|海外|export|tariff|关税|本地化|localiz",
    r"客户|enterprise|采购|procurement|合同|contract|roi|成本",
    r"市场份额|market share|渠道|channel|distribution",
    r"机器人|robot|芯片|chip|semiconductor|电力|energy|数据中心|data center",
]
_TERMS = [re.compile(p, re.IGNORECASE) for p in _BUSINESS_TERMS]
_NOISE = re.compile(r"表情包|明星|综艺|电竞|体育|球赛|celebrity|meme|gossip|horoscope", re.IGNORECASE)


def rule_assess(title: str, content: str, *, tier: int, reliability: int, created_at: str | None) -> dict:
    text = f"{title}\n{content[:2000]}"
    hits = sum(1 for t in _TERMS if t.search(text))
    base = {1: 58, 2: 50, 3: 42, 4: 32}.get(int(tier or 2), 45)
    score = base + min(24, hits * 6) + (reliability - 70) // 5
    if _NOISE.search(text):
        score -= 30
    age_days = 0.0
    if created_at:
        try:
            age_days = (
                utcnow() - datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            ).total_seconds() / 86400
        except ValueError:
            age_days = 0.0
    if age_days > 7:
        score -= 10
    score = max(0, min(100, int(score)))
    return {
        "lane": None,
        "business_value": score,
        "why": f"规则评分（未配置 FAST_MODEL）：T{tier} 来源，命中 {hits} 类商业关键词。",
        "angles": [],
        "keywords": [],
    }


def _pending(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT s.*, so.reliability, so.name AS source_name, so.config_json
        FROM signals s JOIN sources so ON so.id = s.source_id
        WHERE so.kind='story' AND s.dedup_of IS NULL AND s.status IN ('new','filtered')
          AND NOT EXISTS (SELECT 1 FROM story_assessments a WHERE a.signal_id = s.id)
        ORDER BY COALESCE(s.created_at, s.fetched_at) DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def _source_meta(row: sqlite3.Row) -> tuple[int, str | None]:
    cfg = json.loads(row["config_json"] or "{}")
    return int(cfg.get("tier") or 2), cfg.get("lane")


def _store(conn: sqlite3.Connection, signal_id: str, data: dict, *, method: str, model: str | None) -> None:
    lane = data.get("lane") if data.get("lane") in LANES else "OTHER"
    conn.execute(
        """
        INSERT INTO story_assessments(signal_id,lane,business_value,why,angles_json,keywords_json,method,model)
        VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(signal_id) DO UPDATE SET lane=excluded.lane,business_value=excluded.business_value,
          why=excluded.why,angles_json=excluded.angles_json,keywords_json=excluded.keywords_json,
          method=excluded.method,model=excluded.model,created_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
        """,
        (
            signal_id,
            lane,
            max(0, min(100, int(data.get("business_value") or 0))),
            str(data.get("why") or "")[:300],
            json.dumps([str(a)[:80] for a in (data.get("angles") or [])][:3], ensure_ascii=False),
            json.dumps([str(k)[:40] for k in (data.get("keywords") or [])][:6], ensure_ascii=False),
            method,
            model,
        ),
    )
    conn.execute("UPDATE signals SET status='classified' WHERE id=?", (signal_id,))


def assess_pending_stories(
    conn: sqlite3.Connection, *, limit: int = 300, batch: int = 15, job_id: str | None = None
) -> dict:
    rows = _pending(conn, limit)
    stats = {"considered": len(rows), "model": 0, "fixture": 0, "rule": 0}
    if not rows:
        return stats
    by_origin: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        by_origin.setdefault(r["origin"], []).append(r)
    for origin, group in by_origin.items():
        provider = resolve_llm("FAST_MODEL", origin)
        for start in range(0, len(group), batch):
            chunk = group[start : start + batch]
            results: dict[str, dict] = {}
            model_name: str | None = None
            if provider is not None:
                payload = {
                    "items": [
                        {
                            "id": r["id"],
                            "external_id": r["external_id"],
                            "source": r["source_name"],
                            "source_lane": _source_meta(r)[1],
                            "title": r["title"],
                            "text": (r["content"] or "")[:1500],
                            "published_at": r["created_at"],
                        }
                        for r in chunk
                    ]
                }
                try:
                    data, model_name = provider.chat_json(
                        "FAST_MODEL",
                        ASSESS_SYSTEM,
                        json.dumps(payload, ensure_ascii=False),
                        task="assess_stories",
                        conn=conn,
                        job_id=job_id,
                    )
                    for item in data.get("items") or []:
                        if isinstance(item, dict) and item.get("id"):
                            results[str(item["id"])] = item
                except Exception:  # model failure must not block the brief: fall back to rules for this chunk
                    results = {}
                    model_name = None
            for r in chunk:
                tier, source_lane = _source_meta(r)
                item = results.get(r["id"])
                if item:
                    if not item.get("lane") and source_lane:
                        item["lane"] = source_lane
                    method = "fixture" if model_name == "fixture" else "model"
                    _store(conn, r["id"], item, method=method, model=model_name)
                    stats[method] += 1
                else:
                    data = rule_assess(
                        r["title"],
                        r["content"] or "",
                        tier=tier,
                        reliability=r["reliability"],
                        created_at=r["created_at"],
                    )
                    data["lane"] = source_lane or "OTHER"
                    _store(conn, r["id"], data, method="rule", model=None)
                    stats["rule"] += 1
            conn.commit()
    return stats


def story_created_at(row: sqlite3.Row | dict) -> datetime:
    value = row["created_at"] or row["fetched_at"]
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return utcnow()
