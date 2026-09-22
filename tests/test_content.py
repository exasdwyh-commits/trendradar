import sqlite3
from pathlib import Path

import trendradar.services.media as media_mod
from trendradar.content import create_blank_document, get_document, restore_version, save_document
from trendradar.db import init_db

ROOT=Path(__file__).resolve().parents[1]


def db():
    conn=sqlite3.connect(":memory:")
    conn.row_factory=sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn,ROOT/"schema.sql")
    return conn


def test_blank_document_creates_first_version():
    conn=db()
    doc_id=create_blank_document(conn,"测试文章")
    doc=get_document(conn,doc_id)
    assert doc is not None
    assert doc["title"]=="测试文章"
    assert doc["current_version"]==1
    assert doc["current"]["content_json"]["type"]=="doc"


def test_save_and_restore_are_append_only():
    conn=db()
    doc_id=create_blank_document(conn,"v1")
    save_document(
        conn,doc_id,"v2",{"type":"doc","content":[{"type":"paragraph"}]},
        "<p>第二版</p>","第二版",note="manual"
    )
    assert get_document(conn,doc_id)["current_version"]==2
    restored=restore_version(conn,doc_id,1)
    assert restored==3
    doc=get_document(conn,doc_id)
    assert doc["current_version"]==3
    assert len(doc["versions"])==3



def test_image_plan_rejects_untraceable_data_chart(monkeypatch):
    conn=db()
    doc_id=create_blank_document(conn,"测试文章")
    monkeypatch.setattr(media_mod,"slot_enabled",lambda name: True)
    monkeypatch.setattr(
        media_mod,
        "chat_json",
        lambda *args,**kwargs: ({
            "items":[
                {
                    "type":"DATA_CHART",
                    "title":"虚构数据图",
                    "brief":"没有来源的数据",
                    "placement":"正文",
                    "aspect_ratio":"16:9",
                    "prompt":"",
                    "evidence_ids":["fake-id"],
                },
                {
                    "type":"DIAGRAM",
                    "title":"机制图",
                    "brief":"只解释逻辑，不补造数字",
                    "placement":"正文",
                    "aspect_ratio":"16:9",
                    "prompt":"Draw a conceptual mechanism diagram without invented metrics.",
                    "evidence_ids":[],
                },
            ]
        },"writer-model"),
    )

    items=media_mod.create_image_plan(conn,doc_id)
    assert len(items)==1
    assert items[0]["type"]=="DIAGRAM"
    row=conn.execute("SELECT * FROM media_assets WHERE document_id=?",(doc_id,)).fetchone()
    assert row["asset_type"]=="DIAGRAM"
    assert row["evidence_ids_json"]=="[]"
