import json

import pytest

from trendradar.core.errors import ValidationFailed
from trendradar.studio import ai, creation, documents, materials


@pytest.fixture()
def agent_project(conn, monkeypatch):
    mid = materials.create_material(
        conn, kind="note", title="Evidence", content="Revenue grew 20%.", origin="live"
    )
    did = documents.create_document(
        conn, title="My article", content_md="My original manuscript.", seed_material_id=mid
    )

    class Writer:
        calls = []
        fail = False
        invalid_quote = False
        change_source = False

        def chat_json(self, slot, system, user, *, task, **kwargs):
            self.calls.append(task)
            payload = json.loads(user)
            if task == "studio_agent_plan":
                return {
                    "title": "My article",
                    "audience": "Business readers",
                    "question": "Why growth?",
                    "proposition": "Demand supports growth",
                    "gaps": ["Need cost evidence"],
                    "excerpts": [
                        {
                            "id": "quote1",
                            "material_id": mid,
                            "fact": "Growth",
                            "quote": "Invented." if self.invalid_quote else "Revenue grew 20%.",
                        }
                    ],
                    "sections": [
                        {"title": title, "goal": "Explain", "evidence_ids": ["quote1"], "target_words": 200}
                        for title in ("Mechanism", "Boundary")
                    ],
                }, "test-writer"
            if task == "studio_section":
                if self.fail:
                    raise RuntimeError("secret upstream failure")
                if self.change_source:
                    materials.update_material(conn, mid, {"content": "Changed evidence."})
                return {"content_md": f"{payload['section']['title']}: Revenue grew 20%."}, "test-writer"
            if task == "studio_review":
                assert "## Mechanism" in payload["content_md"]
                return {"issues": []}, "test-writer"
            assert task == "studio_variant"
            assert "## Mechanism" in payload["context"]["content_md"]
            return {
                "title": "Platform title",
                "content_md": "Revenue grew 20%.",
                "meta": {"tags": ["business"]},
            }, "test-writer"

    writer = Writer()
    monkeypatch.setattr(creation, "writing_provider", lambda mode: writer)
    monkeypatch.setattr(ai, "writing_provider", lambda mode: writer)
    return did, mid, writer


def planned(conn, project):
    from trendradar.studio import agent

    did, _, _ = project
    run = agent.start(conn, did, "Write a grounded article", ["xiaohongshu"])
    run = agent.advance(conn, did, run["id"], run["revision"])
    assert run["status"] == "awaiting_outline"
    return run


def confirmed(conn, project):
    from trendradar.studio import agent

    run = planned(conn, project)
    return agent.confirm(conn, project[0], run["id"], run["revision"], run["state"]["proposal"])


def finish(conn, did, run):
    from trendradar.studio import agent

    for _ in range(8):
        if run["status"] not in ("planning", "drafting", "reviewing", "variants"):
            return run
        run = agent.advance(conn, did, run["id"], run["revision"])
    pytest.fail("Agent did not reach a checkpoint")


def test_agent_requires_confirmation_and_adoption_then_snapshots_original(conn, agent_project):
    from trendradar.studio import agent

    did, _, writer = agent_project
    run = planned(conn, agent_project)
    assert agent.get_latest(conn, did)["id"] == run["id"]
    assert agent.advance(conn, did, run["id"], run["revision"])["status"] == "awaiting_outline"
    assert writer.calls == ["studio_agent_plan"]
    assert creation.get_workspace(conn, did)["revision"] == 0
    run = agent.confirm(conn, did, run["id"], run["revision"], run["state"]["proposal"])
    run = finish(conn, did, run)
    assert run["status"] == "awaiting_adoption"
    assert writer.calls == [
        "studio_agent_plan",
        "studio_section",
        "studio_section",
        "studio_review",
        "studio_variant",
    ]
    assert documents.get_document(conn, did)["content_md"] == "My original manuscript."
    assert not documents.get_document(conn, did)["variants"]
    run = agent.adopt(conn, did, run["id"], run["revision"])
    doc = documents.get_document(conn, did)
    assert run["status"] == "completed"
    assert doc["content_md"].startswith("## Mechanism")
    assert doc["variants"][0]["platform"] == "xiaohongshu"
    assert all(s["content_md"] for s in creation.get_workspace(conn, did)["plan"]["sections"])
    assert documents.get_version(conn, did, doc["current_version"])["content_md"] == "My original manuscript."
    assert not doc["publications"]
    assert agent.adopt(conn, did, run["id"], run["revision"])["status"] == "completed"
    assert len(documents.get_document(conn, did)["variants"]) == 1


def test_plan_warnings_check_claims_against_selected_quotes_not_metadata(conn, agent_project, monkeypatch):
    from trendradar.studio import agent

    did, _, writer = agent_project
    original = writer.chat_json
    claim = "20%"

    def respond(*args, **kwargs):
        output, model = original(*args, **kwargs)
        output["proposition"] = f"Demand supports {claim} growth"
        return output, model

    monkeypatch.setattr(writer, "chat_json", respond)
    run = planned(conn, agent_project)
    assert run["state"]["warnings"] == []
    claim = "99%"
    run = agent.start(conn, did, "Check evidence", [], restart=True)
    run = agent.advance(conn, did, run["id"], run["revision"])
    assert len(run["state"]["warnings"]) == 1
    assert "99" in run["state"]["warnings"][0]


def test_retry_keeps_completed_sections_and_never_leaks_upstream_error(conn, agent_project):
    from trendradar.studio import agent

    did, _, writer = agent_project
    run = confirmed(conn, agent_project)
    run = agent.advance(conn, did, run["id"], run["revision"])
    writer.fail = True
    run = agent.advance(conn, did, run["id"], run["revision"])
    assert run["status"] == "failed"
    assert "secret" not in run["state"]["error"]
    assert len(run["state"]["drafts"]) == 1
    writer.fail = False
    run = finish(conn, did, agent.advance(conn, did, run["id"], run["revision"]))
    assert run["status"] == "awaiting_adoption"
    assert len(run["state"]["drafts"]) == 2


def test_changed_manuscript_cannot_be_overwritten_by_old_agent(conn, agent_project):
    from trendradar.studio import agent

    did, _, _ = agent_project
    run = finish(conn, did, confirmed(conn, agent_project))
    documents.update_document(conn, did, {"content_md": "A newer manual edit."})
    with pytest.raises(ValidationFailed, match="变化"):
        agent.adopt(conn, did, run["id"], run["revision"])
    assert documents.get_document(conn, did)["content_md"] == "A newer manual edit."
    assert not documents.get_document(conn, did)["variants"]


def test_source_changed_during_generation_is_not_adopted(conn, agent_project):
    from trendradar.studio import agent

    did, _, writer = agent_project
    run = confirmed(conn, agent_project)
    writer.change_source = True
    run = agent.advance(conn, did, run["id"], run["revision"])
    assert run["status"] == "failed"
    assert not run["state"]["drafts"]
    assert documents.get_document(conn, did)["content_md"] == "My original manuscript."


def test_duplicate_or_busy_steps_do_not_call_the_model(conn, agent_project):
    from trendradar.studio import agent

    did, _, writer = agent_project
    run = agent.start(conn, did, "Write", [])
    assert agent.start(conn, did, "Different", ["zhihu"])["id"] == run["id"]
    conn.execute(
        "UPDATE writing_agent_runs SET lease_until=99999999999,lease_token='other' WHERE id=?", (run["id"],)
    )
    conn.commit()
    with pytest.raises(ValidationFailed):
        agent.advance(conn, did, run["id"], run["revision"])
    assert writer.calls == []
    conn.execute("UPDATE writing_agent_runs SET lease_until=0 WHERE id=?", (run["id"],))
    conn.commit()
    updated = agent.advance(conn, did, run["id"], run["revision"])
    with pytest.raises(ValidationFailed):
        agent.confirm(conn, did, updated["id"], run["revision"], updated["state"]["proposal"])
    assert writer.calls == ["studio_agent_plan"]


def test_invented_quotes_and_unknown_platforms_are_rejected(conn, agent_project):
    from trendradar.studio import agent

    did, _, writer = agent_project
    with pytest.raises(ValidationFailed):
        agent.start(conn, did, "Write", ["unknown"])
    writer.invalid_quote = True
    run = agent.start(conn, did, "Write", [])
    run = agent.advance(conn, did, run["id"], run["revision"])
    assert run["status"] == "failed"
    assert creation.get_workspace(conn, did)["excerpts"] == []
    assert creation.get_workspace(conn, did)["revision"] == 0


def test_adoption_is_atomic_when_platform_save_fails(conn, agent_project):
    from trendradar.studio import agent

    did, _, _ = agent_project
    run = finish(conn, did, confirmed(conn, agent_project))
    conn.execute(
        "CREATE TRIGGER fail_variant BEFORE INSERT ON platform_variants BEGIN SELECT RAISE(ABORT, 'test failure'); END"
    )
    conn.commit()
    before = documents.get_document(conn, did)["current_version"]
    with pytest.raises(Exception, match="test failure"):
        agent.adopt(conn, did, run["id"], run["revision"])
    assert documents.get_document(conn, did)["content_md"] == "My original manuscript."
    assert documents.get_document(conn, did)["current_version"] == before
    assert agent.get_latest(conn, did)["status"] == "awaiting_adoption"


def test_offline_demo_runs_through_all_checkpoints(conn):
    from trendradar.studio import agent

    mid = materials.create_material(conn, kind="note", title="Demo", content="Demo evidence.", origin="mock")
    did = documents.create_document(conn, title="Demo manuscript", seed_material_id=mid)
    run = agent.start(conn, did, "Demo only", ["zhihu"])
    run = agent.advance(conn, did, run["id"], run["revision"])
    assert run["status"] == "awaiting_outline"
    assert run["state"]["model"] == "fixture"
    run = agent.confirm(conn, did, run["id"], run["revision"], run["state"]["proposal"])
    run = finish(conn, did, run)
    assert run["status"] == "awaiting_adoption"
    assert run["state"]["review"]["output"]["issues"]
    assert documents.get_document(conn, did)["content_md"] == ""


def test_agent_api_is_read_only_until_requested(conn, agent_project):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from trendradar.api.studio import build_router

    did, _, writer = agent_project
    app = FastAPI()
    app.include_router(build_router(lambda: conn))
    with TestClient(app) as client:
        changes = conn.total_changes
        assert client.get(f"/api/documents/{did}/agent").json() is None
        assert conn.total_changes == changes
        result = client.post(
            f"/api/documents/{did}/agent/start", json={"instruction": "Grounded writing", "platforms": []}
        )
        assert result.status_code == 200
        run = result.json()
        assert writer.calls == []
        result = client.post(
            f"/api/documents/{did}/agent/advance", json={"run_id": run["id"], "revision": run["revision"]}
        )
        assert result.status_code == 200
        assert result.json()["status"] == "awaiting_outline"
