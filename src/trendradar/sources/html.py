"""HTML listing pages (newsrooms, blogs, regulators) that have no usable feed. Ported from TrendRadar 3.1.

The list page is fetched once, same-site links matching `include` are discovered, and the first
`enrich_limit` articles are opened to get summary/body/date. Everything else keeps only title + URL.
"""

from __future__ import annotations

from datetime import timedelta

from ..core.timeutil import utcnow
from .article import discover_links, extract_article, parse_url_date
from .base import BaseAdapter, FetchResult, RawSignal, SearchQuery
from .http import client


class HtmlListAdapter(BaseAdapter):
    adapter_id = "html"
    type = "story"

    def fetch_latest(self) -> FetchResult:
        cfg = self.config
        if not cfg.url:
            return FetchResult(warnings=[f"{self.id}: url missing"])
        result = FetchResult()
        cutoff = utcnow() - timedelta(days=cfg.window_days)
        with client() as c:
            response = c.get(cfg.url)
            response.raise_for_status()
            links = discover_links(
                cfg.url, response.text, include=cfg.include, limit=max(cfg.max_per_round * 2, 10)
            )
            for index, (fallback_title, url) in enumerate(links):
                title, summary, content, published, author = fallback_title, "", "", None, None
                if index < cfg.enrich_limit:
                    try:
                        page = c.get(url)
                        page.raise_for_status()
                        article = extract_article(page.text, fallback_title)
                        title, summary, content = (
                            article.title or fallback_title,
                            article.summary,
                            article.content,
                        )
                        published, author = article.published, article.author
                    except Exception as exc:  # one bad article must not fail the source
                        result.warnings.append(f"{self.id}: enrich failed for {url}: {type(exc).__name__}")
                published = published or parse_url_date(url)
                if published is not None and published < cutoff:
                    continue
                result.signals.append(
                    RawSignal(
                        external_id=url,
                        source=self.id,
                        adapter=self.adapter_id,
                        source_type=self.type,
                        url=url,
                        title=title,
                        content=(content or summary)[:12000],
                        author=author,
                        created_at=published,
                        fetched_at=utcnow(),
                        metadata={"summary": summary} if summary else {},
                    )
                )
                if len(result.signals) >= cfg.max_per_round:
                    break
        return result

    def search(self, query: SearchQuery) -> FetchResult:
        needle = query.text.lower()
        latest = self.fetch_latest()
        latest.signals = [s for s in latest.signals if needle in f"{s.title} {s.content}".lower()][
            : query.limit
        ]
        return latest
