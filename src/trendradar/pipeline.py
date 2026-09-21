from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from .cluster import cluster_titles
from .collect import Item, collect_source
from .config import Source
from .scoring import high_confidence_allowed


def sync_sources(conn: sqlite3.Connection, sources: list[Source]) -> None:
    conn.executemany(
        """
        INSERT INTO sources(id,name,lane,role,type,url,include_pattern,enabled,note)
        VALUES(:id,:name,:lane,:role,:type,:url,:include_pattern,:enabled,:note)
        ON CONFLICT(id) DO UPDATE SET
          name=excluded.name,lane=excluded.lane,role=excluded.role,type=excluded.type,
          url=excluded.url,include_pattern=excluded.include_pattern,
          enabled=excluded.enabled,note=excluded.note
        """,
        [{
            "id": s.id, "name": s.name, "lane": s.lane, "role": s.role, "type": s.type,
            "url": s.url, "include_pattern": s.include_pattern,
            "enabled": 1 if s.enabled else 0, "note": s.note,
        } for s in sources],
    )
    conn.commit()


def store_item(conn: sqlite3.Connection, item: Item) -> bool:
    before = conn.total_changes
    payload = asdict(item)
    payload["published_at"] = item.published_at.isoformat() if item.published_at else None
    conn.execute(
        """
        INSERT OR IGNORE INTO intelligence(
          id,source_id,title,url,canonical_url,published_at,summary,kind,
          source_role,lane,freshness_score,evidence_score,commercial_score,title_hash
        ) VALUES(
          :id,:source_id,:title,:url,:canonical_url,:published_at,:summary,'CLAIM',
          :source_role,:lane,:freshness_score,:evidence_score,:commercial_score,:title_hash
        )
        """,
        payload,
    )
    conn.commit()
    return conn.total_changes > before


def collect_all(conn: sqlite3.Connection, sources: list[Source], timeout: float = 18, limit: int = 25) -> dict:
    stats = {"sources_ok": 0, "sources_failed": 0, "items_seen": 0, "items_new": 0, "failures": []}
    for source in sources:
        if not source.enabled:
            continue
        try:
            items = collect_source(source, timeout=timeout, limit=limit)
            stats["sources_ok"] += 1
            for item in items:
                stats["items_seen"] += 1
                if store_item(conn, item):
                    stats["items_new"] += 1
        except Exception as exc:
            stats["sources_failed"] += 1
            stats["failures"].append({"source": source.id, "error": str(exc)[:180]})
    return stats


def rebuild_clusters(conn: sqlite3.Connection, lookback_limit: int = 500) -> int:
    rows = conn.execute(
        """
        SELECT id,title FROM intelligence
        WHERE origin='live'
        ORDER BY COALESCE(published_at,collected_at) DESC
        LIMIT ?
        """,
        (lookback_limit,),
    ).fetchall()
    clusters = cluster_titles([(r["id"], r["title"]) for r in rows])
    conn.execute("DELETE FROM cluster_items")
    conn.execute("DELETE FROM story_clusters")
    for cluster in clusters:
        cluster_id = hashlib.sha256("|".join(sorted(cluster.item_ids)).encode()).hexdigest()[:24]
        first = conn.execute("SELECT lane FROM intelligence WHERE id=?", (cluster.item_ids[0],)).fetchone()
        conn.execute(
            "INSERT INTO story_clusters(id,canonical_title,lane) VALUES(?,?,?)",
            (cluster_id, cluster.title, first["lane"]),
        )
        conn.executemany(
            "INSERT INTO cluster_items(cluster_id,intelligence_id) VALUES(?,?)",
            [(cluster_id, item_id) for item_id in cluster.item_ids],
        )
    conn.commit()
    return len(clusters)


def rebuild_candidates(conn: sqlite3.Connection) -> int:
    clusters = conn.execute(
        """
        SELECT sc.id,sc.canonical_title,sc.lane,
               MAX(i.evidence_score) AS evidence,
               MAX(i.freshness_score) AS freshness,
               MAX(i.commercial_score) AS commercial,
               COUNT(DISTINCT i.source_id) AS source_count
        FROM story_clusters sc
        JOIN cluster_items ci ON ci.cluster_id=sc.id
        JOIN intelligence i ON i.id=ci.intelligence_id
        GROUP BY sc.id
        """
    ).fetchall()
    conn.execute("DELETE FROM candidates")
    for row in clusters:
        roles = {
            r["source_role"] for r in conn.execute(
                """
                SELECT DISTINCT i.source_role FROM cluster_items ci
                JOIN intelligence i ON i.id=ci.intelligence_id
                WHERE ci.cluster_id=?
                """,
                (row["id"],),
            )
        }
        evidence_ok = high_confidence_allowed(roles)
        cognition = min(100.0, row["evidence"] * 0.35 + row["commercial"] * 0.45 + row["freshness"] * 0.20)
        diversity_bonus = min(12.0, max(0, row["source_count"] - 1) * 6.0)
        content = min(100.0, row["commercial"] * 0.60 + row["freshness"] * 0.25 + diversity_bonus)
        action = "WRITE" if evidence_ok and content >= 70 else "TRACK" if content >= 52 else "SKIP"
        cid = hashlib.sha256(f"candidate|{row['id']}".encode()).hexdigest()[:24]
        conn.execute(
            """
            INSERT INTO candidates(
              id,cluster_id,title,event_summary,cognition_score,content_score,action,generated_by
            ) VALUES(?,?,?,?,?,?,?,'rule')
            """,
            (cid,row["id"],row["canonical_title"],row["canonical_title"],round(cognition,2),round(content,2),action),
        )
    conn.commit()
    return len(clusters)


def today(conn: sqlite3.Connection, limit: int = 3) -> list[dict]:
    rows = conn.execute(
        """
        SELECT c.*,
          (SELECT COUNT(*) FROM cluster_items ci WHERE ci.cluster_id=c.cluster_id) AS evidence_items
        FROM candidates c
        WHERE c.action != 'SKIP'
        ORDER BY c.content_score DESC, c.cognition_score DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def run_daily(conn: sqlite3.Connection, sources: list[Source], timeout: float = 18, limit: int = 25) -> dict:
    run_id = uuid.uuid4().hex
    started = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO runs(id,run_type,started_at,status) VALUES(?,?,?,'RUNNING')",
        (run_id,"daily",started),
    )
    conn.commit()
    try:
        collection = collect_all(conn, sources, timeout=timeout, limit=limit)
        cluster_count = rebuild_clusters(conn)
        candidate_count = rebuild_candidates(conn)
        stats = {"collection": collection, "clusters": cluster_count, "candidates": candidate_count}
        conn.execute(
            "UPDATE runs SET finished_at=?,status='SUCCESS',stats_json=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(),json.dumps(stats,ensure_ascii=False),run_id),
        )
        conn.commit()
        return stats
    except Exception as exc:
        conn.execute(
            "UPDATE runs SET finished_at=?,status='FAILED',error=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(),str(exc),run_id),
        )
        conn.commit()
        raise
