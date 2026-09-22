import sqlite3
from pathlib import Path

import trendradar.content as content
import trendradar.services.publishing as publishing_mod
import trendradar.writing as writing
from trendradar.db import init_db

ROOT = Path(__file__).resolve().parents[1]


def db():
    conn=sqlite3.connect(":memory:")
    conn.row_factory=sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn,ROOT/"schema.sql")
    conn.execute("INSERT INTO sources(id,name,lane,role,type,url) VALUES('s1','Primary','COMPANY','PRIMARY','rss','https://s1')")
    conn.execute("INSERT INTO sources(id,name,lane,role,type,url) VALUES('s2','Verifier','COMPANY','VERIFIER','rss','https://s2')")
    conn.execute("INSERT INTO story_clusters(id,canonical_title,lane) VALUES('cl','Acme enterprise AI','COMPANY')")
    for iid,sid,role in (("i1","s1","PRIMARY"),("i2","s2","VERIFIER")):
        url=f"https://{sid}/{iid}"
        conn.execute(
            """
            INSERT INTO intelligence(
              id,source_id,title,url,canonical_url,summary,content,kind,source_role,lane,
              freshness_score,evidence_score,commercial_score,title_hash
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                iid,sid,"Acme enterprise AI",url,url,
                "Commercial deployment evidence","Detailed contract and customer evidence",
                "CLAIM",role,"COMPANY",100,90,90,f"h-{iid}",
            ),
        )
        conn.execute("INSERT INTO cluster_items(cluster_id,intelligence_id) VALUES('cl',?)",(iid,))
    conn.execute(
        """
        INSERT INTO candidates(
          id,cluster_id,title,event_summary,action,cognition_status,cognition_score,content_score
        ) VALUES('c','cl','Acme enterprise AI','Acme expands enterprise deployment','WRITE','DONE',80,82)
        """
    )
    conn.commit()
    return conn


def test_full_editorial_flow_with_grounding_and_publication_snapshot(monkeypatch):
    conn=db()

    def fake_editorial_model(slot, system, user, **kwargs):
        task=kwargs.get("task")
        if task=="research":
            return ({
                "facts":[
                    {"text":"Acme has a documented enterprise deployment.","evidence_ids":["i1"],"note":""},
                    {"text":"An independent verifier reports the same commercial event.","evidence_ids":["i2"],"note":""},
                ],
                "claims":[],
                "inferences":[
                    {"text":"Budget may be shifting from chat pilots to workflow execution.","evidence_ids":["i1","i2"],"note":"inference"}
                ],
                "strongest_counter":"The deployment may not convert into durable renewals.",
                "evidence_gap":"Need renewal and expansion revenue.",
            },"research-model")
        if task=="thesis":
            return ({
                "thesis":"Enterprise AI budgets are beginning to reward workflow execution over generic chat access.",
                "support":["Two independent commercial sources support a live deployment."],
                "counter":["Renewal economics remain unproven."],
                "falsification_signal":"Renewal and expansion revenue fail to materialize.",
            },"research-model")
        if task=="writer":
            return ({
                "title":"AI企业采购正在从聊天框走向工作流",
                "outline":["发生了什么","钱流向哪里","最强反方","中国映射"],
                "body":"这是基于已确认研究包生成的测试母稿。",
            },"writer-model")
        if task=="critic":
            return ({
                "factual_issues":[],
                "reasoning_issues":[],
                "strongest_counter":"续费仍需验证。",
                "headline_risk":"",
                "verdict":"PASS",
            },"critic-model")
        raise AssertionError(f"unexpected task: {task}")

    monkeypatch.setattr(writing,"chat_json",fake_editorial_model)

    writing.research_candidate(conn,"c")
    thesis_id=writing.propose_thesis(conn,"c")
    ledger_id=writing.confirm_thesis(conn,thesis_id,"6个月")
    article_id,document_id=writing.draft_article(conn,thesis_id)
    review_id=writing.challenge_article(conn,article_id)

    assert ledger_id and review_id
    assert conn.execute("SELECT status FROM articles WHERE id=?",(article_id,)).fetchone()["status"]=="READY"

    monkeypatch.setattr(publishing_mod,"slot_enabled",lambda name: True)
    monkeypatch.setattr(
        publishing_mod,
        "chat_json",
        lambda *args,**kwargs: ({
            "title":"AI企业采购正在从聊天框走向工作流",
            "content_text":"公众号平台测试版本",
            "content_html":"<p>公众号平台测试版本</p>",
            "metadata":{"summary":"test"},
        },"writer-model"),
    )

    variant_id=content.create_platform_variant(conn,document_id,"WECHAT")
    publication_id=content.mark_variant_published(
        conn,variant_id,"https://example.com/published"
    )

    assert conn.execute(
        "SELECT status FROM publications WHERE id=?",(publication_id,)
    ).fetchone()["status"]=="PUBLISHED"
    assert conn.execute(
        "SELECT COUNT(*) n FROM content_snapshots WHERE publication_id=?",(publication_id,)
    ).fetchone()["n"]==1
    assert conn.execute(
        "SELECT COUNT(*) n FROM research_item_sources"
    ).fetchone()["n"]==4
    assert conn.execute(
        "SELECT COUNT(*) n FROM evidence_links WHERE document_id=?",
        (document_id,),
    ).fetchone()["n"]==2

    snapshot = conn.execute(
        "SELECT snapshot_json FROM content_snapshots WHERE publication_id=?",
        (publication_id,),
    ).fetchone()
    assert snapshot is not None
    import json
    payload=json.loads(snapshot["snapshot_json"])
    assert {item["id"] for item in payload["evidence"]} == {"i1","i2"}
