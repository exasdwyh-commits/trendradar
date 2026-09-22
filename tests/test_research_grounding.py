import sqlite3
from pathlib import Path

import pytest

import trendradar.writing as writing
from trendradar.db import init_db

ROOT = Path(__file__).resolve().parents[1]


def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn, ROOT / "schema.sql")
    conn.execute(
        """
        INSERT INTO sources(id,name,lane,role,type,url)
        VALUES('s1','Primary','COMPANY','PRIMARY','rss','https://s1')
        """
    )
    conn.execute(
        """
        INSERT INTO sources(id,name,lane,role,type,url)
        VALUES('s2','Verifier','COMPANY','VERIFIER','rss','https://s2')
        """
    )
    conn.execute(
        "INSERT INTO story_clusters(id,canonical_title,lane) VALUES('cl','Acme expands enterprise AI','COMPANY')"
    )
    for iid,sid,url in (
        ("i1","s1","https://s1/a"),
        ("i2","s2","https://s2/a"),
    ):
        conn.execute(
            """
            INSERT INTO intelligence(
              id,source_id,title,url,canonical_url,summary,content,kind,source_role,lane,
              freshness_score,evidence_score,commercial_score,title_hash
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                iid,sid,"Acme expands enterprise AI",url,url,
                "Acme disclosed a new enterprise deployment and contract.",
                "The source provides concrete commercial details.",
                "CLAIM","PRIMARY" if sid=="s1" else "VERIFIER","COMPANY",
                100,90,90,f"h-{iid}",
            ),
        )
        conn.execute(
            "INSERT INTO cluster_items(cluster_id,intelligence_id) VALUES('cl',?)",
            (iid,),
        )
    conn.execute(
        """
        INSERT INTO candidates(id,cluster_id,title,action,cognition_status)
        VALUES('c','cl','Acme expands enterprise AI','WRITE','DONE')
        """
    )
    conn.commit()
    return conn


def test_research_drops_untraceable_fact_and_persists_provenance(monkeypatch):
    conn = db()

    def fake_chat_json(*args, **kwargs):
        return ({
            "facts":[
                {"text":"Two-source verified fact","evidence_ids":["i1","i2"],"note":""},
                {"text":"Invented source fact","evidence_ids":["does-not-exist"],"note":""},
            ],
            "claims":[
                {"text":"Company says deployment will reduce cost","evidence_ids":["i1"],"note":"company claim"}
            ],
            "inferences":[
                {"text":"This may shift workflow software budgets","evidence_ids":["i1","i2"],"note":"research inference"}
            ],
            "strongest_counter":"Deployment may remain a pilot.",
            "evidence_gap":"Need renewal data.",
        },"research-model")

    monkeypatch.setattr(writing,"chat_json",fake_chat_json)
    rid = writing.research_candidate(conn,"c")
    research = writing.latest_research(conn,"c")

    assert rid
    assert len(research["facts"]) == 1
    assert research["facts"][0]["evidence_ids"] == ["i1","i2"]
    assert research["grounding"]["evidence_count"] == 2
    assert "自动丢弃" in research["evidence_gap"]

    items = conn.execute(
        "SELECT kind,text FROM research_items WHERE research_id=? ORDER BY kind,text",
        (rid,),
    ).fetchall()
    assert len(items) == 3
    links = conn.execute(
        """
        SELECT COUNT(*) n FROM research_item_sources ris
        JOIN research_items ri ON ri.id=ris.research_item_id
        WHERE ri.research_id=?
        """,
        (rid,),
    ).fetchone()["n"]
    assert links == 5


def test_thesis_requires_two_grounded_evidence_items(monkeypatch):
    conn = db()
    conn.execute(
        """
        INSERT INTO research(
          id,candidate_id,facts_json,claims_json,inferences_json,strongest_counter,evidence_gap,generated_by
        ) VALUES('r','c',?,?,?,'','','test')
        """,
        (
            '[{"text":"Only one grounded fact","evidence_ids":["i1"],"note":""}]',
            '[]',
            '[]',
        ),
    )
    conn.commit()

    def should_not_call(*args, **kwargs):
        raise AssertionError("model should not be called before grounding gate")

    monkeypatch.setattr(writing,"chat_json",should_not_call)
    with pytest.raises(ValueError, match="2 grounded units"):
        writing.propose_thesis(conn,"c")


def test_grounded_research_allows_thesis_generation(monkeypatch):
    conn = db()
    conn.execute(
        """
        INSERT INTO research(
          id,candidate_id,facts_json,claims_json,inferences_json,strongest_counter,evidence_gap,generated_by
        ) VALUES('r','c',?,?,?,'','','test')
        """,
        (
            '[{"text":"Fact A","evidence_ids":["i1"],"note":""},'
            '{"text":"Fact B","evidence_ids":["i2"],"note":""}]',
            '[]',
            '[]',
        ),
    )
    conn.commit()

    def fake_chat_json(*args, **kwargs):
        return ({
            "thesis":"Enterprise AI spend is moving toward workflow execution.",
            "support":["Fact A","Fact B"],
            "counter":["Pilot conversion may remain weak."],
            "falsification_signal":"Renewal rates fail to improve.",
        },"thesis-model")

    monkeypatch.setattr(writing,"chat_json",fake_chat_json)
    tid = writing.propose_thesis(conn,"c")
    row = conn.execute("SELECT * FROM theses WHERE id=?",(tid,)).fetchone()
    assert row["status"] == "PENDING"
