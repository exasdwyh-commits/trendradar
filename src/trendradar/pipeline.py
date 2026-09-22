from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .cluster import similarity
from .collect import Item, collect_source
from .config import Source
from .scoring import high_confidence_allowed


def sync_sources(conn: sqlite3.Connection, sources: list[Source]) -> None:
    conn.executemany(
        """
        INSERT INTO sources(
          id,name,lane,role,type,url,include_pattern,tier,reliability,business_value,
          noise,accuracy,max_per_round,enabled,note
        )
        VALUES(
          :id,:name,:lane,:role,:type,:url,:include_pattern,:tier,:reliability,:business_value,
          :noise,:accuracy,:max_per_round,:enabled,:note
        )
        ON CONFLICT(id) DO UPDATE SET
          name=excluded.name,lane=excluded.lane,role=excluded.role,type=excluded.type,
          url=excluded.url,include_pattern=excluded.include_pattern,tier=excluded.tier,
          reliability=excluded.reliability,business_value=excluded.business_value,
          noise=excluded.noise,accuracy=excluded.accuracy,max_per_round=excluded.max_per_round,
          enabled=excluded.enabled,note=excluded.note
        """,
        [{
            "id": s.id, "name": s.name, "lane": s.lane, "role": s.role, "type": s.type,
            "url": s.url, "include_pattern": s.include_pattern,
            "tier": s.tier, "reliability": s.reliability,
            "business_value": s.business_value, "noise": s.noise,
            "accuracy": s.accuracy, "max_per_round": s.max_per_round,
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
          id,source_id,title,url,canonical_url,published_at,summary,content,kind,
          source_role,lane,freshness_score,evidence_score,commercial_score,title_hash
        ) VALUES(
          :id,:source_id,:title,:url,:canonical_url,:published_at,:summary,:content,'CLAIM',
          :source_role,:lane,:freshness_score,:evidence_score,:commercial_score,:title_hash
        )
        """,
        payload,
    )
    conn.commit()
    return conn.total_changes > before


def _health_success(conn: sqlite3.Connection, source_id: str, item_count: int, latency_ms: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO source_health(source_id,last_attempt_at,last_success_at,last_error,consecutive_failures,last_item_count,latency_ms)
        VALUES(?,?,?,NULL,0,?,?)
        ON CONFLICT(source_id) DO UPDATE SET
          last_attempt_at=excluded.last_attempt_at,last_success_at=excluded.last_success_at,
          last_error=NULL,consecutive_failures=0,last_item_count=excluded.last_item_count,
          latency_ms=excluded.latency_ms
        """,
        (source_id,now,now,item_count,latency_ms),
    )


def _health_failure(conn: sqlite3.Connection, source_id: str, error: str, latency_ms: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO source_health(source_id,last_attempt_at,last_error,consecutive_failures,last_item_count,latency_ms)
        VALUES(?,?,?,1,0,?)
        ON CONFLICT(source_id) DO UPDATE SET
          last_attempt_at=excluded.last_attempt_at,last_error=excluded.last_error,
          consecutive_failures=source_health.consecutive_failures+1,last_item_count=0,
          latency_ms=excluded.latency_ms
        """,
        (source_id,now,error[:500],latency_ms),
    )


def collect_all(
    conn: sqlite3.Connection,
    sources: list[Source],
    timeout: float = 18,
    limit: int = 18,
    enrich_limit: int = 6,
) -> dict:
    stats = {"sources_ok": 0, "sources_failed": 0, "items_seen": 0, "items_new": 0, "failures": []}
    for source in sources:
        if not source.enabled:
            continue
        started = time.perf_counter()
        try:
            source_limit = min(limit, source.max_per_round or limit)
            items = collect_source(source, timeout=timeout, limit=source_limit, enrich_limit=enrich_limit)
            latency = int((time.perf_counter() - started) * 1000)
            _health_success(conn, source.id, len(items), latency)
            stats["sources_ok"] += 1
            for item in items:
                stats["items_seen"] += 1
                if store_item(conn, item):
                    stats["items_new"] += 1
        except Exception as exc:
            latency = int((time.perf_counter() - started) * 1000)
            _health_failure(conn, source.id, str(exc), latency)
            stats["sources_failed"] += 1
            stats["failures"].append({"source": source.id, "error": str(exc)[:180]})
        conn.commit()
    return stats


def _existing_clusters(conn: sqlite3.Connection, lane: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT sc.id,sc.canonical_title
        FROM story_clusters sc
        WHERE sc.lane=?
        ORDER BY sc.updated_at DESC
        LIMIT 200
        """,
        (lane,),
    ).fetchall()


def cluster_unassigned(conn: sqlite3.Connection, threshold: float = 0.42, limit: int = 800) -> int:
    rows = conn.execute(
        """
        SELECT i.id,i.title,i.lane
        FROM intelligence i
        LEFT JOIN cluster_items ci ON ci.intelligence_id=i.id
        WHERE ci.intelligence_id IS NULL AND i.origin='live'
        ORDER BY COALESCE(i.published_at,i.collected_at) ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    created = 0
    cache: dict[str, list] = {}
    for row in rows:
        lane = row["lane"]
        candidates = cache.setdefault(lane, list(_existing_clusters(conn, lane)))
        best = None
        best_score = 0.0
        for cluster in candidates:
            score = similarity(row["title"], cluster["canonical_title"])
            if score > best_score:
                best, best_score = cluster, score
        if best is not None and best_score >= threshold:
            cluster_id = best["id"]
        else:
            cluster_id = hashlib.sha256(f"{lane}|{row['title'].lower()}".encode()).hexdigest()[:24]
            conn.execute(
                "INSERT OR IGNORE INTO story_clusters(id,canonical_title,lane) VALUES(?,?,?)",
                (cluster_id,row["title"],lane),
            )
            candidates.append({"id": cluster_id, "canonical_title": row["title"]})
            created += 1
        conn.execute(
            "INSERT OR IGNORE INTO cluster_items(cluster_id,intelligence_id) VALUES(?,?)",
            (cluster_id,row["id"]),
        )
        conn.execute("UPDATE story_clusters SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (cluster_id,))
        if conn.execute("SELECT id FROM candidates WHERE cluster_id=?", (cluster_id,)).fetchone():
            conn.execute(
                "UPDATE candidates SET cognition_status='PENDING',updated_at=CURRENT_TIMESTAMP WHERE cluster_id=?",
                (cluster_id,),
            )
    conn.commit()
    return created


def upsert_candidates(conn: sqlite3.Connection) -> int:
    clusters = conn.execute(
        """
        SELECT sc.id,sc.canonical_title,sc.lane,
               MAX(i.evidence_score) evidence,
               MAX(i.freshness_score) freshness,
               MAX(i.commercial_score) commercial,
               COUNT(DISTINCT i.source_id) source_count
        FROM story_clusters sc
        JOIN cluster_items ci ON ci.cluster_id=sc.id
        JOIN intelligence i ON i.id=ci.intelligence_id
        GROUP BY sc.id
        """
    ).fetchall()
    touched = 0
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
        existing = conn.execute("SELECT id,cognition_status FROM candidates WHERE id=?", (cid,)).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE candidates SET
                  title=?,cognition_score=?,content_score=?,
                  action=CASE WHEN cognition_status='DONE' THEN action ELSE ? END,
                  updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (row["canonical_title"],round(cognition,2),round(content,2),action,cid),
            )
        else:
            conn.execute(
                """
                INSERT INTO candidates(
                  id,cluster_id,title,event_summary,cognition_score,content_score,action,generated_by
                ) VALUES(?,?,?,?,?,?,?,'rule')
                """,
                (cid,row["id"],row["canonical_title"],row["canonical_title"],round(cognition,2),round(content,2),action),
            )
        touched += 1
    conn.commit()
    return touched


def today(conn: sqlite3.Connection, limit: int = 3) -> list[dict]:
    rows = conn.execute(
        """
        SELECT c.*,
          (SELECT COUNT(*) FROM cluster_items ci WHERE ci.cluster_id=c.cluster_id) evidence_items
        FROM candidates c
        WHERE c.action != 'SKIP'
        ORDER BY
          CASE c.action WHEN 'WRITE' THEN 0 WHEN 'TRACK' THEN 1 WHEN 'HOLD' THEN 2 ELSE 3 END,
          c.content_score DESC,c.cognition_score DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def run_daily(
    conn: sqlite3.Connection,
    sources: list[Source],
    timeout: float = 18,
    limit: int = 18,
    enrich_limit: int = 6,
    output_dir: str | Path = "output/daily",
    fast_limit: int = 40,
    cognition_limit: int = 12,
    candidate_snapshot_limit: int = 20,
    lookback_hours: int = 72,
) -> dict:
    from .brief import write_daily_brief
    from .cognition import analyze_pending
    from .fast_rank import refine_candidates
    from .evaluation import ensure_blind_round, freeze_candidate_run
    from .trends import world_model_update

    run_id = uuid.uuid4().hex
    started = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO runs(id,run_type,started_at,status) VALUES(?,?,?,'RUNNING')",
        (run_id,"daily",started),
    )
    conn.commit()
    try:
        collection = collect_all(conn, sources, timeout=timeout, limit=limit, enrich_limit=enrich_limit)
        new_clusters = cluster_unassigned(conn)
        candidate_count = upsert_candidates(conn)
        fast_rank = refine_candidates(conn, limit=fast_limit)
        cognition = analyze_pending(conn, limit=cognition_limit)
        candidate_run_id = freeze_candidate_run(
            conn,
            run_id,
            lookback_hours=lookback_hours,
            max_items=candidate_snapshot_limit,
        )
        blind_round_id = ensure_blind_round(conn, candidate_run_id)
        world_model = world_model_update(conn)
        brief_path = write_daily_brief(conn, output_dir)
        stats = {
            "collection": collection,
            "new_clusters": new_clusters,
            "candidates_touched": candidate_count,
            "fast_rank": fast_rank,
            "cognition": cognition,
            "candidate_run_id": candidate_run_id,
            "blind_round_id": blind_round_id,
            "world_model": world_model,
            "daily_brief": str(brief_path),
        }
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
