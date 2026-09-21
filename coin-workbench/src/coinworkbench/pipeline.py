from __future__ import annotations

import sqlite3
from dataclasses import asdict

from .collect import Item, collect_rss
from .config import Source


def sync_sources(conn: sqlite3.Connection, sources: list[Source]) -> None:
    conn.executemany(
        """
        INSERT INTO sources(id,name,lane,role,type,url,enabled)
        VALUES(:id,:name,:lane,:role,:type,:url,:enabled)
        ON CONFLICT(id) DO UPDATE SET
          name=excluded.name,
          lane=excluded.lane,
          role=excluded.role,
          type=excluded.type,
          url=excluded.url,
          enabled=excluded.enabled
        """,
        [
            {
                "id": s.id, "name": s.name, "lane": s.lane, "role": s.role,
                "type": s.type, "url": s.url, "enabled": 1 if s.enabled else 0,
            }
            for s in sources
        ],
    )
    conn.commit()


def store_item(conn: sqlite3.Connection, item: Item) -> bool:
    before = conn.total_changes
    payload = asdict(item)
    payload["published_at"] = item.published_at.isoformat() if item.published_at else None
    payload["content_kind"] = "CLAIM"
    conn.execute(
        """
        INSERT OR IGNORE INTO intelligence(
          id,source_id,title,url,canonical_url,published_at,summary,
          content_kind,source_role,lane,freshness_score,evidence_score,title_hash
        ) VALUES (
          :id,:source_id,:title,:url,:canonical_url,:published_at,:summary,
          :content_kind,:source_role,:lane,:freshness_score,:evidence_score,:title_hash
        )
        """,
        payload,
    )
    conn.commit()
    return conn.total_changes > before


def collect_all(conn: sqlite3.Connection, sources: list[Source]) -> dict:
    stats = {"sources": 0, "items_seen": 0, "items_new": 0, "skipped_page_sources": 0}
    for source in sources:
        if not source.enabled:
            continue
        if source.type != "rss":
            stats["skipped_page_sources"] += 1
            continue
        stats["sources"] += 1
        for item in collect_rss(source):
            stats["items_seen"] += 1
            if store_item(conn, item):
                stats["items_new"] += 1
    return stats
