import sqlite3
from pathlib import Path

from trendradar.collect import make_item
from trendradar.config import Source
from trendradar.db import init_db
from trendradar.pipeline import cluster_unassigned, store_item, upsert_candidates

ROOT = Path(__file__).resolve().parents[1]


def memory_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn, ROOT / "schema.sql")
    conn.execute(
        "INSERT INTO sources(id,name,lane,role,type,url) VALUES('x','X','COMPANY','VERIFIER','rss','https://x.test')"
    )
    return conn


def test_incremental_cluster_is_stable_when_new_evidence_arrives():
    conn = memory_db()
    source = Source("x","X","COMPANY","VERIFIER","rss","https://x.test")
    a = make_item(source,"OpenAI signs major enterprise contract with retailer","https://x.test/a","contract")
    b = make_item(source,"Retailer signs major enterprise contract with OpenAI","https://x.test/b","contract")
    store_item(conn,a)
    cluster_unassigned(conn,threshold=.35)
    upsert_candidates(conn)
    first = conn.execute("SELECT cluster_id FROM candidates").fetchone()["cluster_id"]
    store_item(conn,b)
    cluster_unassigned(conn,threshold=.35)
    upsert_candidates(conn)
    rows = conn.execute("SELECT DISTINCT cluster_id FROM cluster_items").fetchall()
    assert len(rows) == 1
    assert rows[0]["cluster_id"] == first


def test_new_evidence_marks_cognition_pending():
    conn = memory_db()
    source = Source("x","X","COMPANY","VERIFIER","rss","https://x.test")
    a = make_item(source,"OpenAI signs major enterprise contract with retailer","https://x.test/a","contract")
    store_item(conn,a); cluster_unassigned(conn,threshold=.35); upsert_candidates(conn)
    conn.execute("UPDATE candidates SET cognition_status='DONE'")
    b = make_item(source,"Retailer signs major enterprise contract with OpenAI","https://x.test/b","contract")
    store_item(conn,b); cluster_unassigned(conn,threshold=.35); upsert_candidates(conn)
    assert conn.execute("SELECT cognition_status FROM candidates").fetchone()["cognition_status"] == "PENDING"
