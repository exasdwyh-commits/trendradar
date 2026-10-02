"""Bugs surfaced by enabling mypy."""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest

from trendradar.core.errors import NotFound


def test_set_status_on_missing_opportunity_is_404_not_typeerror(conn):
    from trendradar.opportunities import set_status

    with pytest.raises(NotFound) as info:
        set_status(conn, "missing-id", "watching")
    assert info.value.details == {"id": "missing-id"}


def test_rss_struct_time_is_read_as_utc():
    from calendar import timegm

    stamp = time.strptime("2026-09-30 08:15:00", "%Y-%m-%d %H:%M:%S")
    assert datetime.fromtimestamp(timegm(stamp), tz=UTC) == datetime(2026, 9, 30, 8, 15, tzinfo=UTC)


def test_article_multi_valued_attributes():
    from trendradar.sources.article import discover_links, extract_article

    html = (
        '<html><head><meta property="og:title" content="A  title"><meta name="author" content="Ann">'
        '<meta property="article:published_time" content="2026-09-30T08:00:00Z"></head>'
        '<body><a class="x y" href="/posts/long-enough-article-title" title="A long enough article title">t</a>'
        "</body></html>"
    )
    article = extract_article(html)
    assert article.title == "A title" and article.author == "Ann" and article.published is not None
    links = discover_links("https://example.com/", html, include=None, limit=5)
    assert links == [("A long enough article title", "https://example.com/posts/long-enough-article-title")]
