from datetime import UTC, datetime

from trendradar.ingestion.store import store_product, store_signal
from trendradar.sources.base import RawProduct, RawSignal


def _sig(ext, url, content, source="mock-reddit"):
    return RawSignal(
        external_id=ext,
        source=source,
        adapter="mock",
        url=url,
        title="t",
        content=content,
        fetched_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        origin="mock",
    )


def _with_sources(conn, mock_adapters):
    from trendradar.sources.registry import sync_sources

    configs, adapters = mock_adapters
    sync_sources(conn, configs, adapters)
    return conn


def test_store_signal_dedups_by_url_hash_and_simhash(conn, mock_adapters):
    _with_sources(conn, mock_adapters)
    text = "I keep re-typing the same client onboarding email every single week and it takes me an hour each time, is there a tool that automates it?"
    assert store_signal(conn, _sig("a", "https://x.test/p/1?utm_source=t", text)) == "inserted"
    assert store_signal(conn, _sig("a", "https://x.test/p/1", text)) == "exists"  # same source+external id
    assert store_signal(conn, _sig("b", "https://x.test/p/1#c", text)) == "duplicate"  # canonical url
    assert store_signal(conn, _sig("c", "https://y.test/other", text.upper())) == "duplicate"  # content hash
    assert store_signal(conn, _sig("d", "https://z.test/other", text + " Thanks!")) == "duplicate"  # simhash
    assert (
        store_signal(
            conn,
            _sig(
                "e",
                "https://w.test/other",
                "Completely different complaint about invoices being paid late by clients, chasing takes hours",
            ),
        )
        == "inserted"
    )
    assert conn.execute("SELECT COUNT(*) FROM signals WHERE dedup_of IS NULL").fetchone()[0] == 2


def test_store_product_aliases_same_domain(conn, mock_adapters):
    _with_sources(conn, mock_adapters)
    now = datetime.now(UTC)
    a = RawProduct(
        external_id="p1",
        source="producthunt",
        adapter="producthunt",
        url="https://ph.test/posts/agentdeck",
        website="https://agentdeck.app",
        name="AgentDeck",
        tagline="x",
        origin="mock",
        fetched_at=now,
    )
    b = RawProduct(
        external_id="gh-1",
        source="github-repos",
        adapter="github_repos",
        url="https://github.com/x/agentdeck",
        website="https://www.agentdeck.app/",
        name="agentdeck",
        tagline="y",
        origin="mock",
        fetched_at=now,
    )
    assert store_product(conn, a) == "upserted"
    assert store_product(conn, b) == "upserted"
    rows = conn.execute("SELECT alias_of FROM products WHERE external_id='gh-1'").fetchone()
    assert rows["alias_of"] is not None
    assert conn.execute("SELECT COUNT(*) FROM edges WHERE relation='alias_of'").fetchone()[0] == 1
