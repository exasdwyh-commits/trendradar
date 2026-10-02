import json

import numpy as np

from trendradar.providers.classifier import ClassifyInput, RuleClassifier
from trendradar.providers.embeddings import LocalHashEmbedding
from trendradar.providers.llm import FixtureLLM


def test_model_slot_reads_dotenv_and_environment_takes_precedence(tmp_path, monkeypatch):
    from trendradar.providers.llm import load_slot

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "FAST_MODEL_BASE_URL=https://example.com/v1\nFAST_MODEL_API_KEY=test-only\nFAST_MODEL_MODEL=from-file\n",
        encoding="utf-8",
    )
    for suffix in ("BASE_URL", "API_KEY", "MODEL"):
        monkeypatch.delenv(f"FAST_MODEL_{suffix}", raising=False)
    assert load_slot("FAST_MODEL").enabled
    assert load_slot("FAST_MODEL").model == "from-file"
    monkeypatch.setenv("FAST_MODEL_MODEL", "from-process")
    assert load_slot("FAST_MODEL").model == "from-process"


def test_local_embedding_is_deterministic_and_unit_norm():
    emb = LocalHashEmbedding()
    a = emb.embed(["Managing three coding agent sessions is chaos"])[0]
    b = emb.embed(["Managing three coding agent sessions is chaos"])[0]
    assert np.allclose(a, b) and abs(float(np.linalg.norm(a)) - 1.0) < 1e-5
    c = emb.embed(["My invoices are always paid late by clients"])[0]
    assert float(a @ b) > float(a @ c)


def test_rule_classifier_personas():
    rc = RuleClassifier()
    dev = ClassifyInput(
        id="1",
        external_id="x",
        title="Claude Code sessions",
        content="I run three coding agents in different worktrees and lose track of the terminal state",
        rule_score=0.5,
        rule_matches=["asks_for_tool"],
        source="mock-hn",
        origin="mock",
    )
    fl = ClassifyInput(
        id="2",
        external_id="y",
        title="Freelance admin",
        content="As a freelancer I chase late invoices from clients every week",
        rule_score=0.5,
        rule_matches=["time_cost"],
        source="mock-reddit",
        origin="mock",
    )
    out = {c.id: c for c in rc.classify([dev, fl])}
    assert out["1"].persona == "developer" and out["1"].is_pain
    assert out["2"].persona == "freelancer"


def test_fixture_llm_dispatches_by_task_and_resolves_case():
    llm = FixtureLLM()
    payload = {
        "clusters": [
            {
                "id": "c1",
                "signals": [
                    {"external_id": "r-aca-01", "title": "x"},
                    {"external_id": "hn-aca-01", "title": "y"},
                ],
            }
        ]
    }
    data, model = llm.chat_json("FAST_MODEL", "sys", json.dumps(payload), task="label_clusters")
    assert model == "fixture" and data["items"][0]["persona"] == "developer"
    data, _ = llm.chat_json(
        "ANALYSIS_MODEL",
        "sys",
        json.dumps({"signals": [{"id": "s1", "external_id": "r-fw-01"}], "competitors": []}),
        task="analyze_cluster",
    )
    assert data["opportunity"]["title"] and data["scores"]["pain"]["score"] > 0
    data, _ = llm.chat_json(
        "ANALYSIS_MODEL",
        "sys",
        json.dumps({"signals": [{"id": "s1", "external_id": "nope"}], "competitors": []}),
        task="analyze_cluster",
    )
    assert "error" in data
