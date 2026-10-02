import json
from datetime import UTC

from trendradar.analysis import classify_pending
from trendradar.clustering import cluster_pending_signals, embed_pending_signals
from trendradar.ingestion.runner import collect
from trendradar.providers.embeddings import get_embedder
from trendradar.sources.registry import sync_sources


def test_demo_signals_form_three_pure_clusters(conn, fixture_llm, mock_adapters):
    configs, adapters = mock_adapters
    sync_sources(conn, configs, adapters)
    collect(conn, [a for a in adapters if a.type == "demand"])
    classify_pending(conn, min_rule_score=0.15)
    emb = get_embedder()
    embed_pending_signals(conn, emb, min_relevance=40)
    stats = cluster_pending_signals(conn, emb, threshold=0.10)
    assert stats.created == 3
    rows = conn.execute(
        "SELECT pci.cluster_id, s.metadata_json FROM pain_cluster_items pci JOIN signals s ON s.id=pci.signal_id"
    ).fetchall()
    by_cluster: dict[str, set] = {}
    for r in rows:
        by_cluster.setdefault(r["cluster_id"], set()).add(json.loads(r["metadata_json"]).get("case"))
    assert all(len(cases) == 1 for cases in by_cluster.values()), by_cluster
    assert "noise" not in {c for cases in by_cluster.values() for c in cases}
    # re-running is idempotent
    again = cluster_pending_signals(conn, emb, threshold=0.10)
    assert again.created == 0 and again.assigned_existing == 0


def test_live_and_mock_signals_never_share_a_cluster(conn, fixture_llm, mock_adapters):
    from datetime import datetime

    from trendradar.ingestion.store import store_signal
    from trendradar.sources.base import RawSignal

    configs, adapters = mock_adapters
    sync_sources(conn, configs, adapters)
    collect(conn, [a for a in adapters if a.type == "demand"])
    # a live signal that is textually identical to a demo signal
    demo = conn.execute(
        "SELECT title, content FROM signals WHERE origin='mock' AND external_id='r-aca-01'"
    ).fetchone()
    live = RawSignal(
        external_id="live-1",
        source="hn",
        adapter="hackernews",
        url="https://news.ycombinator.com/item?id=1",
        title=demo["title"],
        content=demo["content"] + " Same problem here, three terminals and no overview.",
        fetched_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        origin="live",
    )
    assert store_signal(conn, live) == "inserted"
    classify_pending(conn, min_rule_score=0.15)
    emb = get_embedder()
    embed_pending_signals(conn, emb, min_relevance=40)
    cluster_pending_signals(conn, emb, threshold=0.10)
    modes = conn.execute("SELECT data_mode, COUNT(*) n FROM pain_clusters GROUP BY data_mode").fetchall()
    assert {r["data_mode"] for r in modes} == {"mock", "live"}
    assert conn.execute("SELECT COUNT(*) FROM pain_clusters WHERE data_mode='mixed'").fetchone()[0] == 0
