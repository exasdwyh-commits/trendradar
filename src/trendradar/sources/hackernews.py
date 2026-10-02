"""Hacker News via the public Algolia search API (no key required).

Demand-side tier-1 source for V1: comments and Ask HN posts are where developers describe
workarounds, complaints and "is there a tool for…" requests.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from ..core.timeutil import utcnow
from .base import BaseAdapter, Engagement, FetchResult, RawSignal, SearchQuery
from .http import client, get_json

ALGOLIA = "https://hn.algolia.com/api/v1/search"
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str | None) -> str:
    text = _TAG_RE.sub(" ", text or "")
    text = (
        text.replace("&#x27;", "'")
        .replace("&quot;", '"')
        .replace("&gt;", ">")
        .replace("&lt;", "<")
        .replace("&amp;", "&")
    )
    return re.sub(r"\s+", " ", text).strip()


class HackerNewsAdapter(BaseAdapter):
    adapter_id = "hackernews"
    type = "demand"

    def search(self, query: SearchQuery) -> FetchResult:
        since = int((utcnow().timestamp()) - query.window_days * 86400)
        result = FetchResult()
        seen: set[str] = set()
        with client() as c:
            for tags in ("comment", "story"):
                if len(result.signals) >= query.limit:
                    break
                data = get_json(
                    c,
                    ALGOLIA,
                    params={
                        "query": query.text,
                        "tags": tags,
                        "numericFilters": f"created_at_i>{since}",
                        "hitsPerPage": min(100, query.limit),
                    },
                )
                for hit in data.get("hits", []) if isinstance(data, dict) else []:
                    signal = self._to_signal(hit, tags)
                    if signal and signal.external_id not in seen:
                        seen.add(signal.external_id)
                        result.signals.append(signal)
                    if len(result.signals) >= query.limit:
                        break
        return result

    def _to_signal(self, hit: dict, tags: str) -> RawSignal | None:
        object_id = str(hit.get("objectID") or "")
        if not object_id:
            return None
        if tags == "comment":
            content = _clean(hit.get("comment_text"))
            title = _clean(hit.get("story_title")) or "HN comment"
            story_id = hit.get("story_id") or object_id
            url = f"https://news.ycombinator.com/item?id={object_id}"
            parent_url = f"https://news.ycombinator.com/item?id={story_id}"
        else:
            content = _clean(hit.get("story_text")) or _clean(hit.get("title"))
            title = _clean(hit.get("title"))
            url = f"https://news.ycombinator.com/item?id={object_id}"
            parent_url = hit.get("url") or url
        if len(content) < 40:
            return None
        created = hit.get("created_at_i")
        created_at = datetime.fromtimestamp(int(created), tz=UTC) if created else None
        return RawSignal(
            external_id=object_id,
            source=self.id,
            adapter=self.adapter_id,
            url=url,
            title=title,
            content=content[:6000],
            author=hit.get("author"),
            author_id=hit.get("author"),
            created_at=created_at,
            fetched_at=utcnow(),
            engagement=Engagement(
                votes=int(hit.get("points") or 0), comments=int(hit.get("num_comments") or 0)
            ),
            metadata={"hn_type": tags, "parent_url": parent_url, "story_id": hit.get("story_id")},
            origin="live",
        )
