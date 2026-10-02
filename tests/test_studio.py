"""Phase-2 creation platform: migration, story assessment, brief, documents/versions, AI actions, publishing."""

from __future__ import annotations

import sqlite3

import pytest

from trendradar.core.errors import NotConfigured, NotFound, ValidationFailed

# ── migration ────────────────────────────────────────────────────────────────


def test_migration_upgrades_v2_database(tmp_path):
    """A pre-phase-2 database (schema v2) must upgrade in place and keep its rows."""
    from trendradar.db.connection import connect
    from trendradar.db.migrate import MIGRATIONS_DIR, migrate, schema_version

    path = tmp_path / "old.db"
    conn = connect(path)
    for name in ("0001_init.sql", "0002_today_picks.sql"):
        conn.executescript((MIGRATIONS_DIR / name).read_text(encoding="utf-8"))
    conn.execute("PRAGMA user_version=2")
    conn.execute(
        "INSERT INTO sources(id,name,kind,adapter,mode,enabled,config_json) VALUES('s1','S','demand','mock','mock',1,'{}')"
    )
    conn.commit()
    assert schema_version(conn) == 2
    applied = migrate(conn)
    assert applied == [3, 4, 5, 6, 7, 8]
    assert schema_version(conn) == 8
    job_columns = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    assert {"heartbeat_at", "owner"} <= job_columns
    # rebuilt sources table kept its row and now accepts the story kind
    assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1
    conn.execute(
        "INSERT INTO sources(id,name,kind,adapter,mode,enabled,config_json) VALUES('s2','T','story','rss','live',1,'{}')"
    )
    for table in (
        "story_assessments",
        "brief_items",
        "materials",
        "documents",
        "document_versions",
        "ai_actions",
    ):
        conn.execute(f"SELECT 1 FROM {table} LIMIT 1")


# ── seeded studio fixture ────────────────────────────────────────────────────


@pytest.fixture()
def seeded(conn: sqlite3.Connection, fixture_llm):
    from trendradar.jobs import seed_demo

    result = seed_demo(conn)
    assert result["status"] in ("success", "partial"), result
    return conn


def test_seed_assesses_stories_and_builds_brief(seeded):
    from trendradar.studio.brief import get_brief

    n_stories = seeded.execute(
        "SELECT COUNT(*) FROM signals s JOIN sources so ON so.id=s.source_id WHERE so.kind='story' AND s.dedup_of IS NULL"
    ).fetchone()[0]
    assessed = seeded.execute("SELECT COUNT(*) FROM story_assessments").fetchone()[0]
    assert n_stories >= 6 and assessed == n_stories
    lanes = {r[0] for r in seeded.execute("SELECT DISTINCT lane FROM story_assessments")}
    assert lanes & {"AI_COMMERCIALIZATION", "INDUSTRY", "COMPANY", "BUSINESS_MODEL", "GLOBALIZATION"}

    page = get_brief(seeded)
    assert page["data_mode"] == "mock"
    assert len(page["sections"]["story"]) >= 3
    assert len(page["sections"]["signal"]) >= 1
    assert len(page["sections"]["opportunity"]) >= 1
    story = page["sections"]["story"][0]
    assert story["why"] and story["angles"] and story["origin"] == "mock" and story["status"] == "new"
    # sorted by worth-writing score
    scores = [s["score"] for s in page["sections"]["story"]]
    assert scores == sorted(scores, reverse=True)


def test_rule_assess_is_deterministic_and_bounded():
    from trendradar.studio.stories import rule_assess

    a = rule_assess(
        "公司宣布利润率提升 20%，推出按结果计费",
        "毛利率上升，定价模式改变",
        tier=1,
        reliability=90,
        created_at=None,
    )
    b = rule_assess(
        "公司宣布利润率提升 20%，推出按结果计费",
        "毛利率上升，定价模式改变",
        tier=1,
        reliability=90,
        created_at=None,
    )
    assert a == b
    assert 0 <= a["business_value"] <= 100 and a["why"]
    assert a["lane"] is None  # rules never guess a lane; the model or a human does
    noisy = rule_assess("招聘启事：诚聘销售", "广告 推广", tier=4, reliability=50, created_at=None)
    assert noisy["business_value"] < a["business_value"]


def test_brief_extend_and_status(seeded):
    from trendradar.studio.brief import extend_item, get_brief, set_item_status
    from trendradar.studio.documents import get_document

    page = get_brief(seeded)
    story = page["sections"]["story"][0]
    signal = page["sections"]["signal"][0]

    saved = set_item_status(seeded, signal["id"], "saved")
    assert saved["status"] == "saved" and saved["material_id"]

    out = extend_item(seeded, story["id"], angle=story["angles"][0])
    doc = get_document(seeded, out["document_id"])
    assert doc["title"] == story["angles"][0]
    assert doc["data_mode"] == "mock"
    assert [m["relation"] for m in doc["materials"]] == ["seed"]
    assert doc["materials"][0]["title"] == story["title"]
    assert doc["content_md"].startswith("> 核心判断") or "## 素材" in doc["content_md"]
    assert not doc["content_md"].lstrip().startswith("# ")  # title is separate, no duplicate H1

    again = get_brief(seeded)
    item = next(i for i in again["sections"]["story"] if i["id"] == story["id"])
    assert item["status"] == "used" and item["document_id"] == out["document_id"]

    dismissed = set_item_status(seeded, again["sections"]["story"][1]["id"], "dismissed")
    assert dismissed["status"] == "dismissed"
    visible = {i["id"] for i in get_brief(seeded)["sections"]["story"]}
    assert dismissed["id"] not in visible
    assert dismissed["id"] in {
        i["id"] for i in get_brief(seeded, include_dismissed=True)["sections"]["story"]
    }

    with pytest.raises(NotFound):
        set_item_status(seeded, "nope", "saved")


# ── documents & versions ─────────────────────────────────────────────────────


def test_document_versions_autosave_manual_restore(conn):
    from trendradar.studio import documents as docs

    doc_id = docs.create_document(conn, title="测试稿", content_md="第一版正文")
    d = docs.get_document(conn, doc_id)
    assert d["current_version"] == 1 and d["versions"][0]["source"] == "seed"

    # autosave right after creation: content updates, no new snapshot yet (15-minute window)
    docs.update_document(conn, doc_id, {"content_md": "第一版正文，加了一句。"}, save_mode="autosave")
    d = docs.get_document(conn, doc_id)
    assert d["content_md"].endswith("加了一句。") and d["current_version"] == 1
    assert d["status"] == "draft"  # editing an idea promotes it to draft

    # manual save always creates a named version
    docs.update_document(conn, doc_id, {"content_md": "第二版正文"}, save_mode="manual", note="改完结构")
    d = docs.get_document(conn, doc_id)
    assert d["current_version"] == 2 and d["versions"][0]["note"] == "改完结构"
    assert docs.get_version(conn, doc_id, 2)["content_md"] == "第二版正文"

    # v1 is the creation snapshot; the autosaved text in between was not versioned (by design)
    v1 = docs.get_version(conn, doc_id, 1)
    assert v1["content_md"] == "第一版正文"

    restored = docs.restore_version(conn, doc_id, 1)
    assert restored["content_md"] == "第一版正文"
    # restore snapshots the pre-restore state first, so history is never lost
    sources = [v["source"] for v in restored["versions"]]
    assert "restore" in sources and restored["current_version"] == 3

    with pytest.raises(NotFound):
        docs.get_version(conn, doc_id, 99)

    docs.delete_document(conn, doc_id)
    with pytest.raises(NotFound):
        docs.get_document(conn, doc_id)


def test_word_count_mixed_cjk_and_latin():
    from trendradar.studio.documents import word_count

    assert word_count("中文五个字") == 5
    assert word_count("hello world") == 2
    assert (
        word_count("## 标题\n\n混合 text 一起 count") == 8
    )  # CJK counts per character (标题/混合/一起 = 6) + 2 latin words


def test_material_from_note_and_bind(conn):
    from trendradar.studio import documents as docs
    from trendradar.studio import materials as mats

    m_id = mats.create_material(
        conn, kind="note", title="访谈笔记", content="客户说：价格不是问题，接入成本才是。"
    )
    m = mats.get_material(conn, m_id)
    assert m["origin"] == "manual" and m["kind"] == "note"

    doc_id = docs.create_document(conn, title="x")
    docs.bind_material(conn, doc_id, m_id, relation="support")
    d = docs.get_document(conn, doc_id)
    assert d["materials"][0]["id"] == m_id and d["materials"][0]["relation"] == "support"
    assert d["data_mode"] == "live"  # hand-written notes are real content, never demo
    docs.unbind_material(conn, doc_id, m_id)
    assert docs.get_document(conn, doc_id)["materials"] == []

    hits = mats.list_materials(conn, q="接入成本")
    assert [h["id"] for h in hits] == [m_id]


# ── AI actions ───────────────────────────────────────────────────────────────


def test_ai_actions_on_demo_document_use_fixture_and_flag_numbers(seeded):
    from trendradar.studio import ai
    from trendradar.studio.brief import extend_item, get_brief
    from trendradar.studio.documents import get_document

    page = get_brief(seeded)
    doc_id = extend_item(seeded, page["sections"]["story"][0]["id"])["document_id"]

    angles = ai.run_action(seeded, doc_id, "angles")
    assert angles["generated_by"] == "fixture" and len(angles["output"]["angles"]) >= 2

    outline = ai.run_action(seeded, doc_id, "outline")
    assert outline["output"]["outline_md"].startswith("##")

    draft = ai.run_action(seeded, doc_id, "draft", {"platform": "wechat"})
    assert draft["output"]["content_md"] and not draft["output"]["content_md"].lstrip().startswith("# ")

    rewrite = ai.run_action(
        seeded, doc_id, "rewrite", {"selection": "这是一段需要精简的原文。", "mode": "concise"}
    )
    assert rewrite["output"]["text"]

    titles = ai.run_action(seeded, doc_id, "titles")
    assert len(titles["output"]["titles"]) >= 3

    doc = get_document(seeded, doc_id)
    assert len(doc["ai_actions"]) == 5
    assert all(a["generated_by"] == "fixture" for a in doc["ai_actions"])

    # number guard: digits that appear in neither materials nor the draft are flagged
    warnings = ai.number_warnings("市场规模达到 8888 亿元，增长 45%", ["增长 45%"])
    assert any("8888" in w for w in warnings) and not any("45" in w for w in warnings)

    with pytest.raises(ValidationFailed):
        ai.run_action(seeded, doc_id, "rewrite", {"selection": "", "mode": "concise"})


def test_ai_requires_writing_model_for_live_documents(conn):
    from trendradar.studio import ai
    from trendradar.studio import documents as docs

    doc_id = docs.create_document(conn, title="真实稿", content_md="正文")
    # a document with no demo materials is treated as live → fixture output is not allowed
    with pytest.raises(NotConfigured):
        ai.run_action(conn, doc_id, "outline")


def test_rewrite_sends_output_contract_to_the_model(conn, monkeypatch):
    import json

    from trendradar.studio import ai
    from trendradar.studio.documents import create_document

    class CaptureProvider:
        def chat_json(self, slot, system, user, **kwargs):
            payload = json.loads(user)
            assert '{"text":' in payload["instruction"]
            assert "精简" in payload["instruction"]
            return {"text": "精简后"}, "test-model"

    monkeypatch.setattr(ai, "writing_provider", lambda mode: CaptureProvider())
    doc_id = create_document(conn, title="测试", content_md="原文")
    result = ai.run_action(conn, doc_id, "rewrite", {"selection": "原文", "mode": "concise"})
    assert result["output"]["text"] == "精简后"


def test_empty_model_output_is_not_recorded_as_a_successful_action(conn, monkeypatch):
    from trendradar.studio import ai
    from trendradar.studio.documents import create_document

    class EmptyProvider:
        def chat_json(self, *args, **kwargs):
            return {"unexpected": "wrong shape"}, "test-model"

    monkeypatch.setattr(ai, "writing_provider", lambda mode: EmptyProvider())
    doc_id = create_document(conn, title="测试", content_md="原文")
    with pytest.raises(ValidationFailed, match="模型"):
        ai.run_action(conn, doc_id, "rewrite", {"selection": "原文"})
    assert conn.execute("SELECT COUNT(*) FROM ai_actions").fetchone()[0] == 0


def test_number_guard_checks_small_factual_numbers_but_ignores_list_markers():
    from trendradar.studio.ai import number_warnings

    assert number_warnings("增长 5%，团队有 3 人", ["团队有 3 人"])
    assert not number_warnings("1. 机制\n2. 证据\n3/ 结论", [])


# ── publishing ───────────────────────────────────────────────────────────────


def test_variants_export_and_publications(seeded):
    from trendradar.studio import publishing as pub
    from trendradar.studio.brief import extend_item, get_brief
    from trendradar.studio.documents import get_document, update_document

    page = get_brief(seeded)
    doc_id = extend_item(seeded, page["sections"]["story"][0]["id"])["document_id"]
    update_document(
        seeded, doc_id, {"content_md": "## 一\n\n正文 **重点** 段落。\n\n> 引用"}, save_mode="manual"
    )

    variant = pub.create_variant(seeded, doc_id, "xiaohongshu")
    assert (
        variant["platform"] == "xiaohongshu"
        and variant["content_md"]
        and variant["generated_by"] == "fixture"
    )

    html, media, name = pub.export_document(seeded, doc_id, fmt="html")
    assert "<h2" in html and "style=" in html and media.startswith("text/html") and name.endswith(".html")
    txt, _, _ = pub.export_document(seeded, doc_id, fmt="txt")
    assert "**" not in txt and "重点" in txt
    md, _, name = pub.export_document(seeded, doc_id, fmt="md", variant_id=variant["id"])
    assert name.endswith(".md") and variant["content_md"] in md

    with pytest.raises(ValidationFailed):
        pub.create_variant(seeded, doc_id, "tiktok")

    p = pub.record_publication(seeded, doc_id, platform="wechat", external_url="https://mp.weixin.qq.com/s/x")
    assert p["platform"] == "wechat"
    assert get_document(seeded, doc_id)["status"] == "published"
    center = pub.publish_center(seeded)
    row = next(d for d in center["documents"] if d["id"] == doc_id)
    assert row["published_platforms"] == ["wechat"] and "xiaohongshu" in row["variant_platforms"]

    pub.delete_publication(seeded, p["id"])
    pub.delete_variant(seeded, variant["id"])
    assert get_document(seeded, doc_id)["variants"] == []


def test_markdown_to_wechat_html_inlines_styles():
    from trendradar.studio.publishing import markdown_to_plain, markdown_to_wechat_html

    html = markdown_to_wechat_html("# 标题\n\n段落，有 `代码` 和 [链接](https://a.b)。\n\n- 一\n- 二")
    assert 'style="' in html and "<h1" in html and "<li" in html
    assert (
        markdown_to_plain("**加粗** 和 [链接](https://a.b)") == "加粗 和 链接（https://a.b）"
    )  # URLs survive for platforms without hyperlinks


def test_rebuild_prunes_stale_items_and_drops_mock_once_live_exists(seeded):
    """After a live fetch the demo stories step aside; items the reader acted on survive a rebuild."""
    from datetime import UTC, datetime

    from trendradar.ingestion.store import store_signal
    from trendradar.sources.base import RawSignal
    from trendradar.studio.brief import build_brief, get_brief, set_item_status
    from trendradar.studio.stories import assess_pending_stories

    before = get_brief(seeded)
    assert all(i["origin"] == "mock" for i in before["sections"]["story"])
    kept = set_item_status(seeded, before["sections"]["story"][0]["id"], "saved")

    live_source = seeded.execute(
        "SELECT id, adapter FROM sources WHERE kind='story' AND mode='live' LIMIT 1"
    ).fetchone()
    now = datetime.now(UTC)
    stories = [
        (
            "咖啡连锁品牌财报：加盟店毛利率 52%，供应链收入首次超过门店营收",
            "加盟模式下利润来自供应链而非门店，定价与渠道结构重塑。",
        ),
        (
            "光伏组件出口价格跌破成本线，头部厂商转向储能与海外建厂",
            "产能过剩压缩利润，出海建厂与储能业务成为新的营收来源。",
        ),
        (
            "跨境物流平台上线按里程计费的保险产品，首月保费收入破千万",
            "保险与物流数据结合，按里程定价打开新的利润池。",
        ),
    ]
    for n, (title, content) in enumerate(stories):
        store_signal(
            seeded,
            RawSignal(
                external_id=f"live-{n}",
                source=live_source["id"],
                adapter=live_source["adapter"],
                source_type="story",
                url=f"https://example.com/live-{n}",
                title=title,
                content=content,
                created_at=now,
                fetched_at=now,
                origin="live",
            ),
        )
    seeded.commit()
    assessed = assess_pending_stories(seeded)
    assert assessed["considered"] >= 3

    build_brief(seeded)
    after = get_brief(seeded)
    stories = after["sections"]["story"]
    assert stories and all(i["origin"] == "live" for i in stories if i["status"] == "new")
    # the saved demo item survives, un-acted demo items are gone
    ids = {i["id"] for i in stories}
    assert kept["id"] in ids
    assert sum(1 for i in stories if i["origin"] == "mock") == 1
    assert after["data_mode"] == "mixed"
    # rebuilding again is idempotent
    build_brief(seeded)
    assert len(get_brief(seeded)["sections"]["story"]) == len(stories)
