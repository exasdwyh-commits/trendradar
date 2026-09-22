from __future__ import annotations

import re
from datetime import datetime, timezone

ROLE_BASE = {"PRIMARY": 100.0, "VERIFIER": 86.0, "DISCOVERY": 52.0}

COMMERCIAL_TERMS = {
    "revenue", "profit", "margin", "pricing", "customer", "contract", "enterprise",
    "acquisition", "merger", "funding", "ipo", "capex", "factory", "supply chain",
    "manufacturing", "license", "subscription", "startup", "sales", "market share",
    "roi", "cost", "productivity", "automation", "robot", "agent", "data center",
    "chip", "energy", "export", "tariff", "出海", "营收", "利润", "毛利", "客户",
    "合同", "订单", "工厂", "供应链", "商业模式", "定价", "并购", "融资", "上市",
    "机器人", "自动化", "算力", "芯片", "能源", "出口", "授权", "复购",
}


def evidence_score(
    role: str,
    has_summary: bool,
    has_date: bool,
    reliability: int | float | None = None,
    noise: int | float | None = None,
    accuracy: int | float | None = None,
) -> float:
    """
    Evidence quality is source-aware rather than role-only.

    Role still sets the epistemic class (PRIMARY / VERIFIER / DISCOVERY), while
    source reliability, historical accuracy and noise refine sources within that
    class. This prevents every verifier or every community source from receiving
    the same score.
    """
    role = role.upper()
    role_base = ROLE_BASE.get(role, 0.0)
    rel = float(reliability if reliability is not None else role_base)
    acc = float(accuracy if accuracy is not None else rel)
    n = float(noise if noise is not None else 30.0)

    score = role_base * 0.50 + rel * 0.30 + acc * 0.20
    score -= min(12.0, max(0.0, n) * 0.12)
    if not has_summary:
        score -= 12
    if not has_date:
        score -= 10
    return round(max(0.0, min(100.0, score)), 2)


def freshness_score(published_at: datetime | None, now: datetime | None = None) -> float:
    if published_at is None:
        return 45.0
    now = now or datetime.now(timezone.utc)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    hours = max(0.0, (now - published_at).total_seconds() / 3600)
    if hours <= 24:
        return 100.0
    if hours <= 48:
        return 85.0
    if hours <= 72:
        return 70.0
    if hours <= 168:
        return 50.0
    return 20.0


def commercial_score(
    title: str,
    summary: str = "",
    source_business_value: int | float | None = None,
) -> float:
    text = f"{title} {summary}".lower()
    hits = sum(1 for term in COMMERCIAL_TERMS if term in text)
    numeric = 1 if re.search(
        r"\d+(?:\.\d+)?\s*(?:%|billion|million|亿|万|美元|元)", text
    ) else 0
    raw = 28.0 + hits * 9.0 + numeric * 12.0
    if source_business_value is not None:
        # Source business density is a prior, not the conclusion.
        raw = raw * 0.82 + float(source_business_value) * 0.18
    return round(min(100.0, raw), 2)


def high_confidence_allowed(roles: set[str]) -> bool:
    roles = {r.upper() for r in roles}
    return bool(roles & {"PRIMARY", "VERIFIER"})
