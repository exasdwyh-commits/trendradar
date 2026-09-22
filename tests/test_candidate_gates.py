import sqlite3
from pathlib import Path

from trendradar.db import init_db
from trendradar.pipeline import upsert_candidates

ROOT = Path(__file__).resolve().parents[1]


def db():
    conn=sqlite3.connect(":memory:")
    conn.row_factory=sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn,ROOT/"schema.sql")
    return conn


def add_source(conn, sid, role):
    conn.execute(
        """
        INSERT INTO sources(
          id,name,lane,role,type,url,tier,reliability,business_value,noise,accuracy
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        (sid,sid,"COMPANY",role,"rss",f"https://example.com/{sid}",1,90,90,10,90),
    )


def add_intel(conn, iid, sid, cluster_id):
    conn.execute(
        """
        INSERT INTO intelligence(
          id,source_id,title,url,canonical_url,summary,content,kind,source_role,lane,
          freshness_score,evidence_score,commercial_score,title_hash
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            iid,sid,"Company wins major enterprise contract",
            f"https://example.com/{iid}",f"https://example.com/{iid}",
            "Revenue contract margin customer enterprise","body","CLAIM",
            "PRIMARY" if sid=="p" else "VERIFIER","COMPANY",
            100,95,96,f"h-{iid}",
        ),
    )
    conn.execute("INSERT INTO cluster_items(cluster_id,intelligence_id) VALUES(?,?)",(cluster_id,iid))


def test_single_source_cannot_be_write_even_with_high_scores():
    conn=db()
    add_source(conn,"p","PRIMARY")
    conn.execute("INSERT INTO story_clusters(id,canonical_title,lane) VALUES('cl','Company wins major enterprise contract','COMPANY')")
    add_intel(conn,"i1","p","cl")
    conn.commit()
    upsert_candidates(conn)
    row=conn.execute("SELECT action FROM candidates WHERE cluster_id='cl'").fetchone()
    assert row["action"] == "TRACK"


def test_two_independent_quality_sources_can_be_write():
    conn=db()
    add_source(conn,"p","PRIMARY")
    add_source(conn,"v","VERIFIER")
    conn.execute("INSERT INTO story_clusters(id,canonical_title,lane) VALUES('cl','Company wins major enterprise contract','COMPANY')")
    add_intel(conn,"i1","p","cl")
    add_intel(conn,"i2","v","cl")
    conn.commit()
    upsert_candidates(conn)
    row=conn.execute("SELECT action FROM candidates WHERE cluster_id='cl'").fetchone()
    assert row["action"] == "WRITE"
