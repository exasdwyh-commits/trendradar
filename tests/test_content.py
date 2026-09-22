import sqlite3
from pathlib import Path

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
