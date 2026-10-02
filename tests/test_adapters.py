from datetime import UTC, datetime

from trendradar.sources.base import RawSignal, SearchQuery, SourceConfig
from trendradar.sources.hackernews import HackerNewsAdapter
from trendradar.sources.hotlist import HotlistAdapter, parse_rows
from trendradar.sources.registry import ADAPTERS, sync_sources


def test_registry_loads_all_configured_adapters(mock_adapters):
    configs, adapters = mock_adapters
    assert {c.adapter for c in configs} <= set(ADAPTERS)
    ids = {a.id for a in adapters}
    assert {"mock-reddit", "mock-hn", "mock-github", "producthunt"} <= ids  # PH auto-mocks without a token


def test_mock_adapter_emits_unified_signals(mock_adapters):
    _, adapters = mock_adapters
    reddit = next(a for a in adapters if a.id == "mock-reddit")
    result = reddit.fetch_latest()
    assert result.signals and all(isinstance(s, RawSignal) for s in result.signals)
    s = result.signals[0]
    assert (
        s.origin == "mock"
        and s.source == "mock-reddit"
        and s.url.startswith("http")
        and s.created_at is not None
    )
    assert reddit.health().mode == "mock"


def test_producthunt_mock_trending_and_search(mock_adapters):
    _, adapters = mock_adapters
    ph = next(a for a in adapters if a.id == "producthunt")
    trending = ph.fetch_trending("7d")
    assert len(trending.products) >= 5
    p = trending.products[0]
    assert p.origin == "mock" and p.name and p.url
    hits = ph.search(SearchQuery(text="coding agent sessions", kind="product", limit=5))
    assert hits.products and any("agent" in (x.name + x.tagline).lower() for x in hits.products)


def test_hackernews_hit_mapping_without_network():
    adapter = HackerNewsAdapter(
        SourceConfig(id="hn", name="HN", adapter="hackernews", kind="demand", mode="live")
    )
    hit = {
        "objectID": "123",
        "comment_text": "I keep losing context between coding agent sessions and it is driving me nuts, is there a tool?",
        "story_title": "Ask HN",
        "story_id": "99",
        "author": "x",
        "created_at_i": 1700000000,
        "points": 3,
    }
    s = adapter._to_signal(hit, "comment")
    assert (
        s is not None
        and s.external_id == "123"
        and s.url.endswith("id=123")
        and s.created_at == datetime.fromtimestamp(1700000000, tz=UTC)
    )
    assert adapter._to_signal({"objectID": "1", "comment_text": "short"}, "comment") is None


def test_sync_sources_marks_effective_mode(conn, mock_adapters):
    configs, adapters = mock_adapters
    sync_sources(conn, configs, adapters)
    row = conn.execute("SELECT mode FROM sources WHERE id='producthunt'").fetchone()
    assert row["mode"] == "mock"


def test_hotlist_parse_rows_shapes():
    assert parse_rows({"code": 200, "data": [{"title": "A"}, "junk"]}) == [{"title": "A"}]
    assert parse_rows({"code": 200, "data": {"data": [{"title": "B"}]}}) == [{"title": "B"}]
    assert parse_rows(["not a dict"]) == []
    assert parse_rows({"code": 200, "data": "oops"}) == []


def test_hotlist_row_mapping_without_network():
    adapter = HotlistAdapter(
        SourceConfig(
            id="cn-hotlist",
            name="国内热榜",
            adapter="hotlist",
            kind="story",
            mode="live",
            extra={"boards": ["weibo", "bili", "nope"], "per_board": 5},
        )
    )
    assert adapter.type == "story"
    assert adapter.boards == ["weibo", "bili"] and adapter.per_board == 5
    now = datetime.now(tz=UTC)
    s = adapter._to_signal(
        "weibo", 1, {"title": "某话题冲上热搜", "hot": "1148823", "url": "https://s.weibo.com/x"}, "60s", now
    )
    assert s is not None and s.source_type == "story" and s.engagement.votes == 1148823
    assert s.external_id.startswith("hotlist:weibo:") and s.metadata["rank"] == 1
    assert s.metadata["board_name"] == "微博热搜" and s.created_at == now
    s2 = adapter._to_signal("bili", 2, {"word": "新番上线", "hot_value": 999}, "xxapi", now)
    assert s2 is not None and "search.bilibili.com" in s2.url and s2.engagement.votes == 999
    assert adapter._to_signal("weibo", 3, {"hot": 1}, "60s", now) is None
