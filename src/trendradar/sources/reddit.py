"""Reddit via public JSON endpoints. Optional: requires a descriptive User-Agent and is rate-limited;
failures degrade only this source. Set REDDIT_ENABLED=true and REDDIT_USER_AGENT in .env."""

from __future__ import annotations

from ..core.settings import get_settings
from ..core.timeutil import parse_datetime, utcnow
from .base import AdapterHealth, BaseAdapter, Engagement, FetchResult, RawSignal, SearchQuery
from .http import client, get_json

_WINDOW = {7: "week", 30: "month", 90: "year", 365: "year"}


class RedditAdapter(BaseAdapter):
    adapter_id = "reddit"
    type = "demand"

    def _enabled(self) -> bool:
        settings = get_settings()
        return settings.reddit_enabled and bool(settings.reddit_user_agent)

    def health(self) -> AdapterHealth:
        if not self._enabled():
            return AdapterHealth(ok=False, mode=self.mode, detail="REDDIT_ENABLED/REDDIT_USER_AGENT not set")
        return AdapterHealth(ok=True, mode=self.mode)

    def search(self, query: SearchQuery) -> FetchResult:
        if not self._enabled():
            return FetchResult(warnings=["reddit disabled (set REDDIT_ENABLED=true and REDDIT_USER_AGENT)"])
        t = next((v for k, v in sorted(_WINDOW.items()) if query.window_days <= k), "year")
        result = FetchResult()
        subs = self.config.subreddits or ["SaaS", "Entrepreneur", "webdev", "productivity", "macapps"]
        with client(headers={"User-Agent": get_settings().reddit_user_agent}) as c:
            for sub in subs:
                if len(result.signals) >= query.limit:
                    break
                data = get_json(
                    c,
                    f"https://www.reddit.com/r/{sub}/search.json",
                    params={"q": query.text, "restrict_sr": 1, "sort": "relevance", "t": t, "limit": 50},
                )
                children = data.get("data", {}).get("children", []) if isinstance(data, dict) else []
                for child in children:
                    d = child.get("data", {})
                    text = (d.get("selftext") or "").strip()
                    title = (d.get("title") or "").strip()
                    if not title or d.get("over_18"):
                        continue
                    result.signals.append(
                        RawSignal(
                            external_id=str(d.get("id")),
                            source=self.id,
                            adapter=self.adapter_id,
                            url=f"https://www.reddit.com{d.get('permalink', '')}",
                            title=title,
                            content=(text or title)[:6000],
                            author=d.get("author"),
                            author_id=d.get("author"),
                            created_at=parse_datetime(d.get("created_utc")),
                            fetched_at=utcnow(),
                            engagement=Engagement(
                                votes=int(d.get("score") or 0), comments=int(d.get("num_comments") or 0)
                            ),
                            metadata={"subreddit": sub, "flair": d.get("link_flair_text")},
                        )
                    )
                    if len(result.signals) >= query.limit:
                        break
        return result
