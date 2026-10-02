"""Fixture-backed demand adapter. Each mock source id (mock-reddit, mock-hn, mock-github) serves the
fixture rows whose `source` matches. Everything is stamped origin='mock'."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from ...core.timeutil import utcnow
from ..base import AdapterHealth, BaseAdapter, Engagement, FetchResult, RawSignal, SearchQuery

FIXTURES = Path(__file__).parent / "fixtures"


def load_demand_fixtures() -> list[dict]:
    return json.loads((FIXTURES / "demand_signals.json").read_text(encoding="utf-8"))


def load_story_fixtures() -> list[dict]:
    return json.loads((FIXTURES / "story_signals.json").read_text(encoding="utf-8"))


def load_analysis_fixtures() -> dict:
    return json.loads((FIXTURES / "analysis_fixtures.json").read_text(encoding="utf-8"))


class MockAdapter(BaseAdapter):
    adapter_id = "mock"
    type = "demand"

    def __init__(self, config):
        super().__init__(config)
        self.mode = "mock"

    def _rows(self) -> list[dict]:
        rows = load_story_fixtures() if self.type == "story" else load_demand_fixtures()
        return [r for r in rows if r.get("source") == self.id]

    def _to_signal(self, row: dict) -> RawSignal:
        now = utcnow()
        return RawSignal(
            external_id=row["external_id"],
            source=self.id,
            adapter=row.get("adapter", "mock"),
            source_type=self.type,
            url=row["url"],
            title=row.get("title", ""),
            content=row.get("content", ""),
            author=row.get("author"),
            author_id=row.get("author"),
            created_at=now - timedelta(days=float(row.get("created_days_ago", 0)), hours=3),
            fetched_at=now,
            engagement=Engagement(**row.get("engagement", {})),
            metadata={**row.get("metadata", {}), "case": row.get("case")},
            origin="mock",
        )

    def fetch_latest(self) -> FetchResult:
        return FetchResult(
            signals=[self._to_signal(r) for r in self._rows()], warnings=[f"{self.id}: mock fixtures"]
        )

    def search(self, query: SearchQuery) -> FetchResult:
        words = [w for w in query.text.lower().split() if len(w) > 2]
        rows = [
            r
            for r in self._rows()
            if any(w in f"{r.get('title', '')} {r.get('content', '')}".lower() for w in words)
        ]
        return FetchResult(signals=[self._to_signal(r) for r in rows[: query.limit]])

    def health(self) -> AdapterHealth:
        return AdapterHealth(ok=True, mode="mock", detail="fixtures")
