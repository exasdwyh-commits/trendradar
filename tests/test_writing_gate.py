import sqlite3
from pathlib import Path

import pytest

from trendradar.db import init_db
from trendradar.writing import draft_article

ROOT = Path(__file__).resolve().parents[1]


def test_draft_requires_confirmed_thesis():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn, ROOT / "schema.sql")
    conn.execute("INSERT INTO sources(id,name,lane,role,type,url) VALUES('s','S','COMPANY','PRIMARY','rss','https://s')")
    conn.execute("INSERT INTO story_clusters(id,canonical_title,lane) VALUES('c','x','COMPANY')")
    conn.execute("INSERT INTO candidates(id,cluster_id,title) VALUES('k','c','x')")
    conn.execute("INSERT INTO theses(id,candidate_id,thesis,status,generated_by) VALUES('t','k','x','PENDING','human')")
    with pytest.raises(ValueError, match="confirmed"):
        draft_article(conn,"t")
