"""RSS/Atom feeds (blogs, forums, changelogs, editorial sources). Carried over from TrendRadar 3.1."""

from __future__ import annotations

import re
from calendar import timegm
from datetime import UTC, datetime

import feedparser

from ..core.timeutil import utcnow
from .base import BaseAdapter, FetchResult, RawSignal, SearchQuery
from .http import client

_TAG_RE = re.compile(r"<[^>]+>")


class RssAdapter(BaseAdapter):
    adapter_id = "rss"
    type = "demand"

    def fetch_latest(self) -> FetchResult:
        if not self.config.url:
            return FetchResult(warnings=[f"{self.id}: url missing"])
        with client() as c:
            response = c.get(self.config.url)
            response.raise_for_status()
        parsed = feedparser.parse(response.content)
        result = FetchResult()
        for entry in parsed.entries[: self.config.max_per_round]:
            title = str(entry.get("title", "")).strip()
            url = str(entry.get("link", "")).strip()
            if not title or not url:
                continue
            stamp = entry.get("published_parsed") or entry.get("updated_parsed")
            # feedparser normalises *_parsed to a UTC struct_time
            created = datetime.fromtimestamp(timegm(stamp), tz=UTC) if stamp else None
            summary = _TAG_RE.sub(" ", str(entry.get("summary", "")))
            blocks = entry.get("content") or []
            content = _TAG_RE.sub(" ", " ".join(str(b.get("value", "")) for b in blocks)) or summary
            result.signals.append(
                RawSignal(
                    external_id=str(entry.get("id") or url),
                    source=self.id,
                    adapter=self.adapter_id,
                    source_type=self.type,
                    url=url,
                    title=title,
                    content=re.sub(r"\s+", " ", content).strip()[:6000],
                    author=entry.get("author"),
                    created_at=created,
                    fetched_at=utcnow(),
                )
            )
        return result

    def search(self, query: SearchQuery) -> FetchResult:
        needle = query.text.lower()
        latest = self.fetch_latest()
        latest.signals = [s for s in latest.signals if needle in f"{s.title} {s.content}".lower()][
            : query.limit
        ]
        return latest
