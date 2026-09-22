import sqlite3
from pathlib import Path

import pytest

from trendradar.content import mark_variant_published
from trendradar.db import init_db

ROOT = Path(__file__).resolve().parents[1]


def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn, ROOT / "schema.sql")
    conn.execute("INSERT INTO story_clusters(id,canonical_title,lane) VALUES('cl','Event','COMPANY')")
    conn.execute("INSERT INTO candidates(id,cluster_id,title,action) VALUES('c','cl','Event','WRITE')")
    conn.execute(
        """
        INSERT INTO theses(id,candidate_id,thesis,status,generated_by)
        VALUES('t','c','A falsifiable thesis','CONFIRMED','human')
        """
    )
    conn.execute(
        """
        INSERT INTO articles(id,candidate_id,thesis_id,title,body,status)
        VALUES('a','c','t','Article','Body','CHALLENGE')
        """
    )
    conn.execute(
        """
        INSERT INTO documents(id,article_id,candidate_id,thesis_id,title,status,current_version)
        VALUES('d','a','c','t','Article','REVIEW',0)
        """
    )
    conn.execute(
        """
        INSERT INTO platform_variants(id,document_id,platform,title,status)
        VALUES('v','d','WECHAT','Article','READY')
        """
    )
    conn.commit()
    return conn


def test_ai_article_cannot_publish_before_challenger_pass():
    conn = db()
    with pytest.raises(ValueError, match="Challenger"):
        mark_variant_published(conn, "v")

    conn.execute("UPDATE articles SET status='READY' WHERE id='a'")
    conn.commit()
    publication_id = mark_variant_published(conn, "v", "https://example.com/published")

    assert publication_id
    assert conn.execute("SELECT status FROM publications WHERE id=?", (publication_id,)).fetchone()["status"] == "PUBLISHED"
    assert conn.execute("SELECT COUNT(*) AS n FROM content_snapshots").fetchone()["n"] == 1
