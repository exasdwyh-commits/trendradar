"""ClassifierProvider: is this signal a software/tool pain worth analysing, and who has it?

Implementations: RuleClassifier (always available), LLMClassifier (FAST_MODEL, batched), and the
fixture provider through LLMClassifier when running demo data. Jev/local classifiers plug in here.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Protocol

from ..core.logging import get_logger
from .llm import LLMProvider, get_llm, resolve_llm

log = get_logger("classifier")


@dataclass
class ClassifyInput:
    id: str
    external_id: str
    title: str
    content: str
    rule_score: float
    rule_matches: list[str] = field(default_factory=list)
    source: str = ""
    origin: str = "live"


@dataclass
class Classification:
    id: str
    is_pain: bool
    relevance: float
    persona: str | None
    category: str | None
    confidence: float
    reason: str
    classifier: str
    model: str | None = None


class ClassifierProvider(Protocol):
    name: str

    def classify(
        self, items: list[ClassifyInput], *, conn: sqlite3.Connection | None = None, job_id: str | None = None
    ) -> list[Classification]: ...


PERSONA_KEYWORDS = {
    "developer": [
        "repo",
        "repos",
        "codebase",
        "code",
        "coding",
        "agent",
        "agents",
        "cli",
        "git",
        "terminal",
        "deploy",
        "engineer",
        "engineers",
        "developer",
        "developers",
        "monorepo",
        "worktree",
        "worktrees",
        "branch",
        "prs",
    ],
    "designer": ["figma", "design", "designer", "mockup", "mockups"],
    "marketer": ["ads", "campaign", "campaigns", "seo", "newsletter", "marketing", "ppc"],
    "freelancer": [
        "freelance",
        "freelancer",
        "freelancers",
        "client",
        "clients",
        "invoice",
        "invoices",
        "invoicing",
        "contract",
        "proposal",
        "proposals",
    ],
    "startup_founder": ["startup", "founder", "mrr", "saas", "launch"],
    "small_business_owner": [
        "salon",
        "shop",
        "clinic",
        "cafe",
        "restaurant",
        "customers",
        "appointment",
        "appointments",
        "plumbing",
        "landscaping",
        "bakery",
        "dental",
        "suppliers",
        "no-shows",
        "owner",
    ],
    "ecommerce_seller": ["shopify", "amazon", "orders", "listing", "listings", "etsy"],
    "agency": ["agency", "agencies", "studio"],
}
CATEGORY_KEYWORDS = {
    "developer_tools": [
        "code",
        "coding",
        "repo",
        "repos",
        "codebase",
        "agent",
        "agents",
        "cli",
        "git",
        "github",
        "terminal",
        "ide",
        "worktree",
        "worktrees",
        "migration",
        "refactor",
        "refactors",
        "branch",
        "transcript",
        "transcripts",
    ],
    "ai_tools": ["llm", "gpt", "claude", "codex", "cursor", "prompt", "prompts", "tokens"],
    "productivity": [
        "notes",
        "todo",
        "calendar",
        "workflow",
        "spreadsheet",
        "notion",
        "reporting",
        "reports",
        "admin",
    ],
    "finance": [
        "invoice",
        "invoices",
        "invoicing",
        "payment",
        "payments",
        "tax",
        "expense",
        "expenses",
        "accounting",
        "unpaid",
        "paid",
    ],
    "small_business": [
        "appointment",
        "appointments",
        "customers",
        "reviews",
        "inventory",
        "stock",
        "quote",
        "quotes",
        "quoting",
        "booking",
        "bookings",
        "reminders",
        "suppliers",
        "salon",
        "cafe",
        "clinic",
        "plumbing",
        "landscaping",
        "bakery",
        "dental",
    ],
    "marketing": ["ads", "seo", "newsletter", "campaign", "campaigns", "analytics"],
    "ecommerce": ["shopify", "orders", "listing", "listings", "etsy", "amazon"],
    "design": ["figma", "mockup", "mockups", "design"],
}

_WORD_CACHE: dict[str, re.Pattern] = {}


def _pick(text: str, table: dict[str, list[str]]) -> str | None:
    words = set(re.findall(r"[a-z][a-z0-9'+#-]*", text.lower()))
    best, best_hits = None, 0
    for label, keywords in table.items():
        hits = sum(1 for w in keywords if w in words)
        if hits > best_hits:
            best, best_hits = label, hits
    return best


class RuleClassifier:
    name = "rule"

    def classify(self, items: list[ClassifyInput], *, conn=None, job_id=None) -> list[Classification]:
        out = []
        for it in items:
            text = f"{it.title} {it.content}"
            relevance = min(100.0, it.rule_score * 100)
            first_person = bool(re.search(r"\b(i|we|my|our)\b", text.lower()))
            if first_person:
                relevance = min(100.0, relevance + 8)
            out.append(
                Classification(
                    id=it.id,
                    is_pain=relevance >= 40,
                    relevance=round(relevance, 1),
                    persona=_pick(text, PERSONA_KEYWORDS),
                    category=_pick(text, CATEGORY_KEYWORDS),
                    confidence=0.35,
                    reason="rule lexicon: " + ", ".join(it.rule_matches[:4])
                    if it.rule_matches
                    else "rule lexicon: no pain patterns",
                    classifier=self.name,
                )
            )
        return out


CLASSIFY_SYSTEM = """You triage user-generated text for a software opportunity radar.
For each item decide: is_pain (the author describes a real problem, unmet need, workaround, complaint about a tool, or a request for a tool — not news, not self-promotion, not a release note), relevance 0-100 (how relevant to building a software/AI/tool product for the global market), persona (one of: developer, designer, marketer, freelancer, startup_founder, small_business_owner, ecommerce_seller, agency, consumer, other), category (developer_tools, ai_tools, productivity, finance, small_business, marketing, ecommerce, design, other), confidence 0-1, and a short reason.
Return JSON: {"items":[{"id":"...","is_pain":true,"relevance":85,"persona":"developer","category":"developer_tools","confidence":0.8,"reason":"..."}]}"""


class LLMClassifier:
    name = "llm"

    def __init__(self, provider: LLMProvider | None = None, batch_size: int = 20):
        self.provider = provider
        self.batch_size = batch_size
        self.fallback = RuleClassifier()

    def classify(self, items: list[ClassifyInput], *, conn=None, job_id=None) -> list[Classification]:
        out: list[Classification] = []
        for start in range(0, len(items), self.batch_size):
            batch = items[start : start + self.batch_size]
            provider = self.provider
            if provider is None:
                mode = "mock" if all(b.origin == "mock" for b in batch) else "live"
                provider = resolve_llm("FAST_MODEL", mode)
            if provider is None:
                out.extend(self.fallback.classify(batch))
                continue
            payload = {
                "signals": [
                    {
                        "id": b.id,
                        "external_id": b.external_id,
                        "title": b.title[:200],
                        "content": b.content[:1200],
                        "rule_score": b.rule_score,
                        "source": b.source,
                    }
                    for b in batch
                ]
            }
            try:
                data, model = provider.chat_json(
                    "FAST_MODEL",
                    CLASSIFY_SYSTEM,
                    json.dumps(payload, ensure_ascii=False),
                    task="classify_signals",
                    conn=conn,
                    job_id=job_id,
                )
            except Exception as exc:
                log.warning("classifier batch failed (%s); rule fallback", exc)
                out.extend(self.fallback.classify(batch))
                continue
            by_id = {b.id: b for b in batch}
            got: set[str] = set()
            for row in data.get("items", []) if isinstance(data, dict) else []:
                sid = row.get("id")
                if sid not in by_id:
                    continue
                got.add(sid)
                try:
                    relevance = max(0.0, min(100.0, float(row.get("relevance", 0))))
                    confidence = max(0.0, min(1.0, float(row.get("confidence", 0.5))))
                except (TypeError, ValueError):
                    continue
                out.append(
                    Classification(
                        id=sid,
                        is_pain=bool(row.get("is_pain")),
                        relevance=relevance,
                        persona=row.get("persona"),
                        category=row.get("category"),
                        confidence=confidence,
                        reason=str(row.get("reason") or "")[:300],
                        classifier="fixture" if model == "fixture" else "llm",
                        model=model,
                    )
                )
            missing = [b for b in batch if b.id not in got]
            if missing:
                out.extend(self.fallback.classify(missing))
        return out


def get_classifier() -> ClassifierProvider:
    """LLM-backed when a FAST model (or fixture for mock data) is available, else rules."""
    return LLMClassifier()


def classifier_status() -> dict:
    return {"provider": "llm" if get_llm().slot_enabled("FAST_MODEL") else "rule (+fixture for demo data)"}
