import sqlite3
from pathlib import Path

import pytest

import trendradar.content as content
from trendradar.db import init_db

ROOT=Path(__file__).resolve().parents[1]


def db():
    conn=sqlite3.connect(":memory:")
    conn.row_factory=sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn,ROOT/"schema.sql")
    return conn


def test_selection_edit_is_pure_transform_and_filters_fake_evidence(monkeypatch):
    conn=db()
    document_id=content.create_blank_document(conn,"自主文章")
    before=conn.execute(
        "SELECT COUNT(*) n FROM document_versions WHERE document_id=?",(document_id,)
    ).fetchone()["n"]

    monkeypatch.setattr(content,"slot_enabled",lambda name: True)
    monkeypatch.setattr(
        content,
        "chat_json",
        lambda *args,**kwargs: ({
            "replacement":"更紧凑、逻辑更清楚的一段文字。",
            "used_evidence_ids":["invented-id"],
            "warning":"",
        },"writer-model"),
    )

    result=content.edit_selection(
        conn,document_id,"原始的一段文字","精简并加强逻辑","上文","下文"
    )
    after=conn.execute(
        "SELECT COUNT(*) n FROM document_versions WHERE document_id=?",(document_id,)
    ).fetchone()["n"]

    assert result["replacement"].startswith("更紧凑")
    assert result["used_evidence_ids"] == []
    assert before == after


def test_selection_edit_requires_real_selection(monkeypatch):
    conn=db()
    document_id=content.create_blank_document(conn,"自主文章")
    monkeypatch.setattr(content,"slot_enabled",lambda name: True)
    with pytest.raises(ValueError,match="selected_text"):
        content.edit_selection(conn,document_id,"","精简")
