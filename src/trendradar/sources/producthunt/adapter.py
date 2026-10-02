"""Product Hunt adapter. Modes:
graphql  live API v2 (needs PRODUCTHUNT_TOKEN)
mcp      reserved: same interface backed by an MCP gateway (not wired in V1; raises NotConfigured)
mock     bundled fixtures, origin='mock'
"""

from __future__ import annotations

import json
from pathlib import Path

from ...core.errors import NotConfigured, SourceError
from ...core.settings import get_settings
from ...core.timeutil import days_ago, utcnow
from ..base import (
    AdapterHealth,
    BaseAdapter,
    FetchResult,
    RawProduct,
    SearchQuery,
    SourceConfig,
    TrendingWindow,
)
from .client import ProductHuntClient
from .mapping import post_to_product

FIXTURES = Path(__file__).parent.parent / "mock" / "fixtures"


class ProductHuntAdapter(BaseAdapter):
    adapter_id = "producthunt"
    type = "supply"
    supports_trending = True

    def __init__(self, config: SourceConfig):
        super().__init__(config)
        settings = get_settings()
        self.api_mode = settings.producthunt_mode
        if self.api_mode == "graphql" and not settings.producthunt_token:
            self.api_mode = "mock"
            self.degraded_reason = "PRODUCTHUNT_TOKEN missing → mock"
        else:
            self.degraded_reason = ""
        self.mode = "live" if self.api_mode == "graphql" else "mock"
        self._client: ProductHuntClient | None = None

    # ── infrastructure ──
    def _api(self) -> ProductHuntClient:
        if self.api_mode == "mcp":
            raise NotConfigured("PRODUCTHUNT_MODE=mcp is reserved; use graphql or mock in V1")
        if self._client is None:
            self._client = ProductHuntClient(get_settings().producthunt_token)
        return self._client

    def health(self) -> AdapterHealth:
        if self.api_mode == "mock":
            return AdapterHealth(ok=True, mode="mock", detail=self.degraded_reason or "fixtures")
        try:
            self._api().whoami()
            return AdapterHealth(
                ok=True,
                mode="live",
                detail=f"remaining complexity: {self._client.remaining if self._client else '?'}",
            )
        except (SourceError, NotConfigured) as exc:
            return AdapterHealth(ok=False, mode="live", detail=str(exc))

    def _mock_products(self) -> list[RawProduct]:
        path = FIXTURES / "producthunt_products.json"
        rows = json.loads(path.read_text(encoding="utf-8"))
        out = []
        for row in rows:
            row = dict(row)
            row.setdefault("source", self.id)
            row.setdefault("adapter", self.adapter_id)
            row["fetched_at"] = utcnow()
            row["origin"] = "mock"
            out.append(RawProduct(**row))
        return out

    # ── contract ──
    def fetch_trending(self, window: TrendingWindow = "7d") -> FetchResult:
        if self.api_mode == "mock":
            products = self._mock_products()
            return FetchResult(products=products, warnings=["producthunt: mock fixtures"])
        days = {"7d": 7, "30d": 30, "month": 31}[window]
        nodes = self._api().posts(
            first=self.config.max_per_round, order="VOTES", posted_after=days_ago(days).isoformat()
        )
        return FetchResult(products=[post_to_product(n, source_id=self.id) for n in nodes])

    def fetch_by_topic(self, topic: str, *, days: int = 90, first: int = 40) -> FetchResult:
        if self.api_mode == "mock":
            products = [
                p for p in self._mock_products() if any(topic.lower() in c.lower() for c in p.categories)
            ]
            return FetchResult(products=products)
        nodes = self._api().posts(
            first=first, order="VOTES", posted_after=days_ago(days).isoformat(), topic=topic
        )
        return FetchResult(products=[post_to_product(n, source_id=self.id) for n in nodes])

    def search(self, query: SearchQuery) -> FetchResult:
        """API-side fallback search: resolve topics by name, pull their recent posts.
        The primary semantic search happens locally over the ingested corpus (market layer)."""
        if self.api_mode == "mock":
            needle = query.text.lower().split()
            products = [
                p
                for p in self._mock_products()
                if any(
                    w in f"{p.name} {p.tagline} {p.description} {' '.join(p.categories)}".lower()
                    for w in needle
                )
            ]
            return FetchResult(products=products[: query.limit])
        result = FetchResult()
        topics = self._api().topics(query.text)
        for topic in topics[:2]:
            result.extend(
                self.fetch_by_topic(topic["slug"], days=query.window_days, first=min(40, query.limit))
            )
        return result

    def fetch_latest(self) -> FetchResult:
        result = self.fetch_trending("7d")
        for topic in self.config.topics:
            try:
                result.extend(self.fetch_by_topic(topic, days=self.config.window_days, first=25))
            except (SourceError, NotConfigured) as exc:
                result.warnings.append(f"topic {topic}: {exc}")
        # De-duplicate by external id within the round.
        seen: set[str] = set()
        unique = []
        for p in result.products:
            if p.external_id not in seen:
                seen.add(p.external_id)
                unique.append(p)
        result.products = unique
        return result
