import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch, fixture_llm):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    from trendradar.core.settings import reset_settings

    reset_settings()
    from trendradar.api import create_app
    from trendradar.db.connection import connect
    from trendradar.db.migrate import migrate
    from trendradar.jobs import seed_demo

    app = create_app(static_dir=tmp_path / "nope")
    with TestClient(app) as c:
        conn = connect(tmp_path / "data" / "trendradar.db")
        migrate(conn)
        seed_demo(conn)
        conn.close()
        yield c
    reset_settings()


def test_health_and_settings(client):
    h = client.get("/api/health").json()
    assert h["ok"] and h["counts"]["opportunities"] == 3 and "llm" in h["providers"]
    s = client.get("/api/settings").json()
    assert "FAST_MODEL" in s["models"] and s["pipeline"]["today_min_score"] == 70


def test_creation_workspace_api_round_trip(client, monkeypatch):
    from trendradar.providers.llm import FixtureLLM
    from trendradar.studio import creation

    monkeypatch.setattr(creation, "writing_provider", lambda mode: FixtureLLM())
    material = client.post("/api/materials", json={"title": "Source", "content": "An original fact."}).json()
    doc = client.post("/api/documents", json={"title": "Article", "material_ids": [material["id"]]}).json()
    path = f"/api/documents/{doc['id']}/workspace"
    assert client.get(path).json()["revision"] == 0
    assert (
        client.post(
            path + "/excerpts", json={"material_id": material["id"], "fact": "Fact", "quote": "Invented"}
        ).status_code
        == 422
    )
    excerpt = client.post(
        path + "/excerpts", json={"material_id": material["id"], "fact": "Fact", "quote": "An original fact."}
    ).json()
    state = client.patch(
        path,
        json={
            "revision": 0,
            "changes": {"sections": [{"id": "one", "title": "Section", "evidence_ids": [excerpt["id"]]}]},
        },
    ).json()
    assert client.patch(path, json={"revision": 0, "changes": {"audience": "Stale edit"}}).status_code == 422
    state = client.post(path + "/confirm", json={"revision": state["revision"]}).json()
    candidate = client.post(path + "/sections/one/generate", json={"revision": state["revision"]}).json()
    assert "id" in candidate
    state = client.post(
        path + "/sections/one/adopt", json={"revision": state["revision"], "action_id": candidate["id"]}
    ).json()
    assembled = client.post(path + "/assemble", json={"revision": state["revision"]}).json()
    assert "An original fact." in assembled["content_md"]
    assert client.get(f"/api/documents/{doc['id']}").json()["content_md"] == ""


def test_article_translation_api_and_cache(client, monkeypatch):
    from trendradar.providers.llm import OpenAICompatibleLLM
    from trendradar.studio import translations

    monkeypatch.setattr(translations, "get_llm", OpenAICompatibleLLM)
    mid = client.post(
        "/api/materials", json={"kind": "note", "title": "English report", "content": "Sales grew 20%."}
    ).json()["id"]
    path = f"/api/translations/material/{mid}?scope=full"
    assert client.get(path).json() is None
    assert client.post(path).status_code == 503

    class Translator:
        calls = 0

        def slot_enabled(self, slot):
            return True

        def chat_json(self, *args, **kwargs):
            self.calls += 1
            return {"title": "英文报告", "content": "销量增长 20%。"}, "test-model"

    provider = Translator()
    monkeypatch.setattr(translations, "get_llm", lambda: provider)
    first = client.post(path)
    assert first.status_code == 200 and first.json()["title"] == "英文报告"
    assert client.get(path).json()["cached"]
    assert client.post(path).json()["cached"] and provider.calls == 1
    assert client.get(f"/api/materials/{mid}").json()["content"] == "Sales grew 20%."
    assert client.get("/api/translations/material/missing").status_code == 404


def test_today_radar_and_opportunities(client):
    today = client.get("/api/today").json()
    assert 1 <= len(today["picks"]) <= 5 and today["picks"][0]["title"] == "AI Coding Session Manager"
    assert today["picks"][0]["data_mode"] == "mock" and today["brief_md"].startswith("# Daily Brief")
    radar = client.get("/api/radar?window=30d").json()
    assert len(radar["clusters"]) == 3 and all(len(c["series"]) == 30 for c in radar["clusters"])
    lst = client.get("/api/opportunities?sort=opportunity_score").json()
    assert lst["total"] == 3 and lst["items"][0]["scores"]["pain"]["reason"]
    filtered = client.get("/api/opportunities?persona=freelancer").json()
    assert filtered["total"] == 1
    assert client.get("/api/opportunities?status=bogus").status_code == 422


def test_opportunity_detail_status_and_brief(client):
    oid = client.get("/api/opportunities").json()["items"][0]["id"]
    d = client.get(f"/api/opportunities/{oid}").json()
    assert (
        d["evidence"] and d["pain_signals"] and d["competition"]["competitors"] and d["allowed_transitions"]
    )
    assert all(e["url"] for e in d["evidence"])
    r = client.post(f"/api/opportunities/{oid}/status", json={"status": "watching"})
    assert r.status_code == 200 and r.json()["to"] == "watching"
    r = client.post(f"/api/opportunities/{oid}/status", json={"status": "building"})
    assert r.status_code == 422 and r.json()["error"] == "validation_failed"
    assert client.get(f"/api/opportunities/{oid}/brief").status_code == 404
    b = client.post(f"/api/opportunities/{oid}/brief").json()
    assert b["problem_definition"] and b["core_features"] and b["generated_by"] == "fixture"
    assert client.get(f"/api/opportunities/{oid}/brief").status_code == 200
    assert client.get("/api/opportunities/nope").status_code == 404


def test_cluster_signal_product_endpoints(client):
    oid = client.get("/api/opportunities").json()["items"][0]
    cluster = client.get(f"/api/clusters/{oid['pain_cluster_id']}").json()
    assert cluster["signals"] and cluster["opportunity"]["id"] == oid["id"]
    sig = client.get(f"/api/signals/{cluster['signals'][0]['id']}").json()
    assert sig["classification"] and sig["url"]
    products = client.get("/api/products").json()
    assert len(products["items"]) >= 10 and products["clusters"]
    p = client.get(f"/api/products/{products['items'][0]['id']}").json()
    assert p["name"] and "insights" in p


def test_explore_ask_sources_jobs(client):
    r = client.post("/api/explore", json={"query": "AI coding agent sessions", "live": False}).json()
    assert r["clusters"] and r["products"] and r["data_mode"] == "mock"
    assert client.get(f"/api/explore/{r['session_id']}").json()["status"] == "done"
    a = client.post("/api/ask", json={"question": "What could I build in a weekend for developers?"}).json()
    assert "[opp:" in a["answer_md"] and a["citations"]
    src = client.get("/api/sources").json()["items"]
    assert {s["id"] for s in src} >= {"hn", "producthunt", "mock-reddit"}
    assert client.post("/api/sources/mock-hn/test").json()["ok"]
    assert client.post("/api/sources/reddit/toggle", json={"enabled": False}).json()["enabled"] is False
    jobs = client.get("/api/jobs").json()["items"]
    assert jobs and jobs[0]["status"] == "success" and any(s["step"] == "analyze" for s in jobs[0]["steps"])
    assert client.get("/api/reports").json()["items"]


def test_easel_bridge_http_round_trip(client):
    """Easel 发布桥接的 HTTP 链路：出包 → 回写入账。

    函数级测试看不到路由是否真的挂上了，这条守 404/422 那一类。
    """
    import json
    from pathlib import Path

    # 读接口无副作用：outbox 还没建时，查状态不该把它创建出来
    status = client.get("/api/publish/easel").json()
    outbox = Path(status["outbox"])
    assert status["packages"] == 0
    assert status["easel_publishers"]["wechat"] == "skill-wechat-publisher"
    assert not outbox.exists(), "GET /api/publish/easel 不应创建 outbox 目录"

    doc = client.post(
        "/api/documents",
        json={
            "title": "Easel 桥接稿",
            "content_md": "## 判断\n\n正文足够长，用于出包验证。",
            "target_platform": "wechat",
        },
    ).json()

    # 空正文与不存在的稿件都要挡在出包之前
    empty = client.post("/api/documents", json={"title": "空稿", "target_platform": "wechat"}).json()
    assert client.post(f"/api/documents/{empty['id']}/easel-handoff", json={}).status_code == 422
    assert client.post("/api/documents/not-a-real-id/easel-handoff", json={}).status_code == 404

    first = client.post(f"/api/documents/{doc['id']}/easel-handoff", json={})
    assert first.status_code == 201, first.text
    pkg = first.json()
    assert pkg["handoff"]["easel_publisher"] == "skill-wechat-publisher"
    pkg_dir = Path(pkg["path"])
    assert (pkg_dir / "handoff.json").is_file() and (pkg_dir / "content.md").is_file()
    assert (pkg_dir / "wechat.html").is_file()  # 公众号附排版 HTML

    # 幂等：同稿件同内容重复移交复用同一个包
    again = client.post(f"/api/documents/{doc['id']}/easel-handoff", json={})
    assert again.json()["package"] == pkg["package"]

    # Easel（或人工）发完后写回 result.json，sync 入账；重复 sync 不重复记账
    (pkg_dir / "result.json").write_text(
        json.dumps({"status": "published", "external_url": "https://mp.weixin.qq.com/s/easel-demo"}),
        encoding="utf-8",
    )
    assert client.post("/api/publish/easel/sync").json()["recorded_count"] == 1
    assert client.post("/api/publish/easel/sync").json()["recorded_count"] == 0
    assert client.get("/api/publish/easel").json()["by_status"] == {"recorded": 1}
    ledger = json.dumps(client.get("/api/publish").json(), ensure_ascii=False)
    assert "https://mp.weixin.qq.com/s/easel-demo" in ledger
