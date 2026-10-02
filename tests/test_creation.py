import json

import pytest

from trendradar.core.errors import ValidationFailed
from trendradar.studio import documents, materials


@pytest.fixture()
def project(conn):
    mid = materials.create_material(
        conn, kind="note", title="Report", content="Intro " * 800 + "Revenue grew 20% in 2025.", origin="live"
    )
    did = documents.create_document(conn, title="Article", seed_material_id=mid)
    return did, mid


def test_workspace_revision_and_outline_confirmation(conn, project):
    from trendradar.studio import creation

    did, mid = project
    workspace = creation.get_workspace(conn, did)
    section = {
        "id": "one",
        "title": "Growth",
        "goal": "Explain the mechanism",
        "evidence_ids": [],
        "target_words": 300,
        "content_md": "",
    }
    workspace = creation.save_workspace(conn, did, {"question": "Why growth?", "sections": [section]}, 0)
    with pytest.raises(ValidationFailed, match="更新"):
        creation.save_workspace(conn, did, {"question": "Old tab"}, 0)
    confirmed = creation.confirm_outline(conn, did, workspace["revision"])
    assert confirmed["plan"]["outline_confirmed"]
    changed = creation.save_workspace(
        conn, did, {"sections": [{**section, "goal": "New goal"}]}, confirmed["revision"]
    )
    assert not changed["plan"]["outline_confirmed"]


def test_excerpt_requires_bound_material_and_verbatim_quote(conn, project):
    from trendradar.studio import creation

    did, mid = project
    other = materials.create_material(conn, kind="note", title="Other", content="Unrelated")
    with pytest.raises(ValidationFailed):
        creation.add_excerpt(conn, did, other, "Fact", "Unrelated")
    with pytest.raises(ValidationFailed):
        creation.add_excerpt(conn, did, mid, "Fact", "An invented quote")
    excerpt = creation.add_excerpt(conn, did, mid, "Growth", "Revenue grew 20% in 2025.")
    assert excerpt["source_title"] == "Report" and not excerpt["stale"]
    materials.update_material(conn, mid, {"content": "Revenue declined."})
    assert creation.get_workspace(conn, did)["excerpts"][0]["stale"]


def test_section_reads_selected_evidence_beyond_prefix_and_uses_writing_model(conn, project, monkeypatch):
    from trendradar.studio import creation

    did, mid = project
    excerpt = creation.add_excerpt(conn, did, mid, "Growth", "Revenue grew 20% in 2025.")
    workspace = creation.save_workspace(
        conn,
        did,
        {
            "proposition": "Growth comes from demand",
            "sections": [
                {
                    "id": "one",
                    "title": "Growth",
                    "goal": "Explain",
                    "evidence_ids": [excerpt["id"]],
                    "target_words": 300,
                }
            ],
        },
        0,
    )
    workspace = creation.confirm_outline(conn, did, workspace["revision"])

    class Provider:
        def chat_json(self, slot, system, user, **kwargs):
            self.slot, self.payload = slot, json.loads(user)
            return {"content_md": "Revenue grew 20% in 2025."}, "mimo-test"

    provider = Provider()
    monkeypatch.setattr(creation, "writing_provider", lambda mode: provider)
    monkeypatch.setattr(creation, "writing_slot", lambda: "WRITING_MODEL")
    result = creation.generate_section(conn, did, "one", workspace["revision"])
    assert provider.slot == "WRITING_MODEL"
    assert "Intro" not in json.dumps(provider.payload)
    assert provider.payload["evidence"][0]["quote"] == "Revenue grew 20% in 2025."
    assert result["input_scope"]["evidence_ids"] == [excerpt["id"]]
    assert documents.get_document(conn, did)["content_md"] == ""
    creation.save_workspace(conn, did, {"author_notes": "New personal view"}, workspace["revision"])
    with pytest.raises(ValidationFailed):
        creation.adopt_section(conn, did, "one", result["id"], workspace["revision"])


def test_readiness_flags_skeleton_and_missing_facts(conn, project):
    from trendradar.studio import creation

    did, mid = project
    documents.update_document(conn, did, {"content_md": "## 正文\n【待补充】", "status": "draft"})
    checks = creation.get_workspace(conn, did)["checks"]
    assert any(check["id"] == "placeholders" and not check["ok"] for check in checks)
    assert any(check["id"] == "evidence" and not check["ok"] for check in checks)


def prepared_workspace(conn, project):
    from trendradar.studio import creation

    did, mid = project
    excerpt = creation.add_excerpt(conn, did, mid, "Growth", "Revenue grew 20% in 2025.")
    state = creation.save_workspace(
        conn,
        did,
        {
            "style": "Short sentences",
            "sections": [
                {"id": "one", "title": "Growth", "evidence_ids": [excerpt["id"]], "target_words": 200}
            ],
        },
        0,
    )
    return creation.confirm_outline(conn, did, state["revision"])


def test_adopt_only_section_then_assemble_without_overwriting_manuscript(conn, project, monkeypatch):
    from trendradar.providers.llm import FixtureLLM
    from trendradar.studio import creation

    did, mid = project
    state = prepared_workspace(conn, project)
    monkeypatch.setattr(creation, "writing_provider", lambda mode: FixtureLLM())
    candidate = creation.generate_section(conn, did, "one", state["revision"])
    state = creation.adopt_section(conn, did, "one", candidate["id"], state["revision"])
    assert state["plan"]["outline_confirmed"]
    assert "Revenue grew 20%" in state["plan"]["sections"][0]["content_md"]
    assert conn.execute("SELECT accepted FROM ai_actions WHERE id=?", (candidate["id"],)).fetchone()[0] == 1
    assert creation.assemble(conn, did, state["revision"])["content_md"].startswith("## Growth")
    assert documents.get_document(conn, did)["content_md"] == ""


def test_candidate_cannot_be_adopted_after_material_changes(conn, project, monkeypatch):
    from trendradar.providers.llm import FixtureLLM
    from trendradar.studio import creation

    did, mid = project
    state = prepared_workspace(conn, project)
    monkeypatch.setattr(creation, "writing_provider", lambda mode: FixtureLLM())
    candidate = creation.generate_section(conn, did, "one", state["revision"])
    materials.update_material(conn, mid, {"content": "Updated source"})
    with pytest.raises(ValidationFailed, match="变化"):
        creation.adopt_section(conn, did, "one", candidate["id"], state["revision"])
    assert not creation.get_workspace(conn, did)["plan"]["sections"][0]["content_md"]


@pytest.mark.parametrize(
    "sections", [["bad"], [{"id": [], "title": "Bad"}], [{"title": "Bad", "evidence_ids": [{}]}]]
)
def test_workspace_rejects_invalid_nested_sections(conn, project, sections):
    from trendradar.studio import creation

    with pytest.raises(ValidationFailed):
        creation.save_workspace(conn, project[0], {"sections": sections}, 0)


def test_atomic_save_rejects_a_revision_changed_after_initial_read(conn, project):
    from trendradar.studio import creation

    did, mid = project
    state = creation.save_workspace(conn, did, {"question": "First"}, 0)
    creation.save_workspace(conn, did, {"question": "Second"}, state["revision"])
    with pytest.raises(ValidationFailed):
        creation._save(conn, did, state["plan"], state["revision"])
    assert creation.get_workspace(conn, did)["plan"]["question"] == "Second"


def test_review_preserves_original_and_rejects_unlocated_suggestions(conn, project, monkeypatch):
    from trendradar.studio import creation

    did, mid = project
    documents.update_document(conn, did, {"content_md": "A confident claim."})

    class Reviewer:
        quote = "A confident claim."

        def chat_json(self, *args, **kwargs):
            return {
                "issues": [
                    {"quote": self.quote, "reason": "Evidence is missing", "suggestion": "A tentative claim."}
                ]
            }, "mimo-test"

    reviewer = Reviewer()
    monkeypatch.setattr(creation, "writing_provider", lambda mode: reviewer)
    result = creation.review_document(conn, did)
    assert result["output"]["issues"][0]["quote"] == "A confident claim."
    assert documents.get_document(conn, did)["content_md"] == "A confident claim."
    reviewer.quote = "Not in original"
    with pytest.raises(ValidationFailed, match="定位"):
        creation.review_document(conn, did)


def test_existing_assistant_uses_plan_and_exact_excerpts_instead_of_prefix(conn, project, monkeypatch):
    from trendradar.studio import ai

    prepared_workspace(conn, project)

    class Writer:
        def chat_json(self, slot, system, user, **kwargs):
            payload = json.loads(user)
            assert payload["context"]["plan"]["style"] == "Short sentences"
            assert payload["context"]["materials"] == []
            assert payload["context"]["evidence"][0]["quote"] == "Revenue grew 20% in 2025."
            return {"summary": "Evidence summary"}, "mimo-test"

    monkeypatch.setattr(ai, "writing_provider", lambda mode: Writer())
    assert ai.run_action(conn, project[0], "summary")["output"]["summary"] == "Evidence summary"


def test_platform_version_is_flagged_after_manuscript_changes(conn, project, monkeypatch):
    from trendradar.providers.llm import FixtureLLM
    from trendradar.studio import ai, creation, publishing

    did, mid = project
    documents.update_document(conn, did, {"content_md": "Original body"})
    monkeypatch.setattr(ai, "writing_provider", lambda mode: FixtureLLM())
    publishing.create_variant(conn, did, "wechat")
    assert next(c for c in creation.get_workspace(conn, did)["checks"] if c["id"] == "variants")["ok"]
    documents.update_document(conn, did, {"content_md": "Updated body"})
    assert not next(c for c in creation.get_workspace(conn, did)["checks"] if c["id"] == "variants")["ok"]


def test_ai_action_filters_by_section_evidence(conn, project, monkeypatch):
    from trendradar.studio import ai, creation

    did, mid = project
    # project fixture provides a material with content 'Revenue grew 20% in 2025.'
    e1 = creation.add_excerpt(conn, did, mid, "Growth", "Revenue grew 20% in 2025.")
    e2 = creation.add_excerpt(conn, did, mid, "Demand", "Revenue grew 20%")
    creation.save_workspace(
        conn,
        did,
        {
            "sections": [
                {
                    "id": "sec1",
                    "title": "Section 1",
                    "goal": "Goal 1",
                    "evidence_ids": [e1["id"]],
                    "target_words": 100,
                },
                {
                    "id": "sec2",
                    "title": "Section 2",
                    "goal": "Goal 2",
                    "evidence_ids": [e2["id"]],
                    "target_words": 100,
                },
            ]
        },
        0,
    )

    class SectionWriter:
        def chat_json(self, slot, system, user, **kwargs):
            payload = json.loads(user)
            ev_quotes = [item["quote"] for item in payload["context"]["evidence"]]
            assert "Revenue grew 20% in 2025." in ev_quotes
            assert "Other quote" not in ev_quotes
            assert payload["context"]["section"]["id"] == "sec1"
            return {"summary": "Sec1 summary"}, "mimo-test"

    monkeypatch.setattr(ai, "writing_provider", lambda mode: SectionWriter())
    res = ai.run_action(conn, did, "summary", options={"section_id": "sec1"})
    assert res["output"]["summary"] == "Sec1 summary"
