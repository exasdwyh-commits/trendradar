import json

import pytest

from trendradar.core.errors import ValidationFailed
from trendradar.jobs import seed_demo
from trendradar.opportunities import set_status


def test_seed_demo_produces_three_grounded_opportunities(seeded):
    conn = seeded
    opps = conn.execute("SELECT * FROM opportunities ORDER BY opportunity_score DESC").fetchall()
    assert len(opps) == 3
    assert {o["title"] for o in opps} == {
        "AI Coding Session Manager",
        "Solo Freelancer Money Loop",
        "Zero-Config Automation Recipes for Local Businesses",
    }
    assert opps[0]["title"] == "AI Coding Session Manager"
    assert all(o["data_mode"] == "mock" and o["generated_by"] == "fixture" for o in opps)
    for o in opps:
        dims = {
            r["dimension"]: r
            for r in conn.execute("SELECT * FROM opportunity_scores WHERE opportunity_id=?", (o["id"],))
        }
        assert set(dims) == {
            "pain",
            "demand",
            "growth",
            "competition",
            "gap",
            "monetization",
            "build_ease",
            "distribution",
            "confidence",
        }
        assert all(0 <= d["score"] <= 100 and d["reason"] for d in dims.values())
        ev = conn.execute(
            "SELECT * FROM evidence WHERE subject_type='opportunity' AND subject_id=?", (o["id"],)
        ).fetchall()
        assert ev and all(e["url"] and e["quote"] for e in ev)
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM competition_profiles WHERE pain_cluster_id=?", (o["pain_cluster_id"],)
            ).fetchone()[0]
            == 1
        )
    # every pain signal quote is verbatim from its signal
    for ps in conn.execute(
        "SELECT ps.evidence_quote, s.title, s.content FROM pain_signals ps JOIN signals s ON s.id=ps.signal_id"
    ):
        if ps["evidence_quote"]:
            assert ps["evidence_quote"].lower()[:30] in (ps["title"] + "\n" + ps["content"]).lower()
    picks = conn.execute("SELECT * FROM today_picks").fetchall()
    assert 1 <= len(picks) <= 5
    assert conn.execute("SELECT COUNT(*) FROM reports WHERE kind='daily_brief'").fetchone()[0] == 1
    job = conn.execute("SELECT * FROM jobs ORDER BY started_at DESC LIMIT 1").fetchone()
    assert job["status"] == "success" and json.loads(job["stats_json"])["analyze"]["ok"] == 3
    assert conn.execute("SELECT COUNT(*) FROM ai_runs WHERE task='analyze_cluster'").fetchone()[0] == 3


def test_rerun_is_idempotent_and_versions_bump(seeded):
    conn = seeded
    before = conn.execute("SELECT id, version FROM opportunities").fetchall()
    result = seed_demo(conn)
    assert result["status"] == "success"
    assert result["stats"]["collect"]["signals"]["inserted"] == 0
    after = {r["id"]: r["version"] for r in conn.execute("SELECT id, version FROM opportunities")}
    assert len(after) == 3 and all(after[r["id"]] == r["version"] + 1 for r in before)
    assert conn.execute("SELECT COUNT(*) FROM pain_clusters WHERE session_id IS NULL").fetchone()[0] == 3


def test_lifecycle_transitions(seeded):
    conn = seeded
    oid = conn.execute("SELECT id FROM opportunities LIMIT 1").fetchone()["id"]
    set_status(conn, oid, "watching")
    set_status(conn, oid, "promising")
    with pytest.raises(ValidationFailed):
        set_status(conn, oid, "building")
    set_status(conn, oid, "rejected", note="not for me")
    assert (
        conn.execute("SELECT COUNT(*) FROM opportunity_status_log WHERE opportunity_id=?", (oid,)).fetchone()[
            0
        ]
        == 4
    )


def test_db_source_toggle_survives_sync_and_is_respected(tmp_path):
    from trendradar.core.config import sources_path
    from trendradar.db.connection import connect
    from trendradar.db.migrate import migrate
    from trendradar.sources.registry import (
        build_adapters,
        enabled_adapters,
        load_source_configs,
        sync_sources,
    )

    conn = connect(tmp_path / "toggle.db")
    migrate(conn)
    configs = load_source_configs(sources_path())
    sync_sources(conn, configs, build_adapters(configs))
    assert conn.execute("SELECT enabled FROM sources WHERE id='mock-hn'").fetchone()[0] == 1

    conn.execute("UPDATE sources SET enabled=0 WHERE id='mock-hn'")
    conn.commit()
    sync_sources(conn, configs, build_adapters(configs))  # a later job/startup must not revert the toggle
    assert conn.execute("SELECT enabled FROM sources WHERE id='mock-hn'").fetchone()[0] == 0

    ids = {a.id for a in enabled_adapters(conn, configs, mock_only=True)}
    assert "mock-hn" not in ids and "mock-reddit" in ids
