from __future__ import annotations

import sqlite3


FEEDBACK_WEIGHTS = {
    "OPENED": 1,
    "SAVED": 3,
    "DRAFTED": 5,
    "PUBLISHED": 8,
    "DISMISSED": -6,
}


def ensure_learning_schema(conn: sqlite3.Connection) -> None:
    """Create append-only learning/observability tables without changing core scoring."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS source_health_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
          checked_at TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('SUCCESS','FAILED')),
          item_count INTEGER NOT NULL DEFAULT 0,
          latency_ms INTEGER NOT NULL DEFAULT 0,
          error TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_source_health_history_source_time
          ON source_health_history(source_id, checked_at DESC);
        CREATE INDEX IF NOT EXISTS idx_source_health_history_time
          ON source_health_history(checked_at DESC);

        CREATE TRIGGER IF NOT EXISTS trg_source_health_history_insert
        AFTER INSERT ON source_health
        BEGIN
          INSERT INTO source_health_history(
            source_id, checked_at, status, item_count, latency_ms, error
          ) VALUES(
            NEW.source_id,
            COALESCE(NEW.last_attempt_at, CURRENT_TIMESTAMP),
            CASE WHEN NEW.last_error IS NULL THEN 'SUCCESS' ELSE 'FAILED' END,
            COALESCE(NEW.last_item_count, 0),
            COALESCE(NEW.latency_ms, 0),
            NEW.last_error
          );
        END;

        CREATE TRIGGER IF NOT EXISTS trg_source_health_history_update
        AFTER UPDATE OF last_attempt_at,last_success_at,last_error,consecutive_failures,last_item_count,latency_ms
        ON source_health
        BEGIN
          INSERT INTO source_health_history(
            source_id, checked_at, status, item_count, latency_ms, error
          ) VALUES(
            NEW.source_id,
            COALESCE(NEW.last_attempt_at, CURRENT_TIMESTAMP),
            CASE WHEN NEW.last_error IS NULL THEN 'SUCCESS' ELSE 'FAILED' END,
            COALESCE(NEW.last_item_count, 0),
            COALESCE(NEW.latency_ms, 0),
            NEW.last_error
          );
        END;

        CREATE TABLE IF NOT EXISTS candidate_feedback (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          candidate_id TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
          action TEXT NOT NULL CHECK(action IN ('OPENED','SAVED','DRAFTED','PUBLISHED','DISMISSED')),
          weight INTEGER NOT NULL,
          note TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_candidate_feedback_candidate_time
          ON candidate_feedback(candidate_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_candidate_feedback_time
          ON candidate_feedback(created_at DESC);

        CREATE TRIGGER IF NOT EXISTS trg_publication_feedback
        AFTER UPDATE OF status ON publications
        WHEN NEW.status='PUBLISHED' AND OLD.status!='PUBLISHED'
        BEGIN
          INSERT INTO candidate_feedback(candidate_id, action, weight, note)
          SELECT d.candidate_id, 'PUBLISHED', 8, 'auto:publication'
          FROM platform_variants pv
          JOIN documents d ON d.id=pv.document_id
          WHERE pv.id=NEW.variant_id AND d.candidate_id IS NOT NULL;
        END;
        """
    )


def record_candidate_feedback(
    conn: sqlite3.Connection,
    candidate_id: str,
    action: str,
    note: str = "",
) -> dict:
    normalized = (action or "").strip().upper()
    if normalized not in FEEDBACK_WEIGHTS:
        raise ValueError(
            f"unsupported feedback action: {action}; expected one of {', '.join(FEEDBACK_WEIGHTS)}"
        )
    if not conn.execute("SELECT 1 FROM candidates WHERE id=?", (candidate_id,)).fetchone():
        raise LookupError(f"candidate not found: {candidate_id}")

    cursor = conn.execute(
        """
        INSERT INTO candidate_feedback(candidate_id,action,weight,note)
        VALUES(?,?,?,?)
        """,
        (candidate_id, normalized, FEEDBACK_WEIGHTS[normalized], (note or "")[:1000]),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM candidate_feedback WHERE id=?",
        (cursor.lastrowid,),
    ).fetchone()
    return dict(row)


def recent_candidate_feedback(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    rows = conn.execute(
        """
        SELECT f.*,c.title candidate_title
        FROM candidate_feedback f
        JOIN candidates c ON c.id=f.candidate_id
        ORDER BY f.id DESC
        LIMIT ?
        """,
        (max(1, min(int(limit), 500)),),
    ).fetchall()
    return [dict(row) for row in rows]


def feedback_summary(conn: sqlite3.Connection) -> dict:
    actions = conn.execute(
        """
        SELECT action,COUNT(*) count,SUM(weight) weighted_signal
        FROM candidate_feedback
        GROUP BY action
        ORDER BY count DESC,action ASC
        """
    ).fetchall()
    candidates = conn.execute(
        """
        SELECT c.id,c.title,COUNT(f.id) feedback_count,SUM(f.weight) weighted_signal,
               MAX(f.created_at) last_feedback_at
        FROM candidate_feedback f
        JOIN candidates c ON c.id=f.candidate_id
        GROUP BY c.id,c.title
        ORDER BY weighted_signal DESC,feedback_count DESC,last_feedback_at DESC
        LIMIT 20
        """
    ).fetchall()
    return {
        "actions": [dict(row) for row in actions],
        "candidates": [dict(row) for row in candidates],
    }


def source_health_history(
    conn: sqlite3.Connection,
    *,
    days: int = 7,
    limit: int = 500,
) -> dict:
    safe_days = max(1, min(int(days), 90))
    safe_limit = max(1, min(int(limit), 2000))
    rows = conn.execute(
        """
        SELECT h.*,s.name,s.role,s.lane
        FROM source_health_history h
        JOIN sources s ON s.id=h.source_id
        WHERE datetime(h.checked_at) >= datetime('now', ?)
        ORDER BY h.id DESC
        LIMIT ?
        """,
        (f"-{safe_days} days", safe_limit),
    ).fetchall()
    aggregate = conn.execute(
        """
        SELECT h.source_id,s.name,
               COUNT(*) checks,
               SUM(CASE WHEN h.status='SUCCESS' THEN 1 ELSE 0 END) successes,
               SUM(CASE WHEN h.status='FAILED' THEN 1 ELSE 0 END) failures,
               ROUND(AVG(h.latency_ms),1) avg_latency_ms,
               ROUND(AVG(h.item_count),1) avg_item_count,
               MAX(h.checked_at) last_checked_at
        FROM source_health_history h
        JOIN sources s ON s.id=h.source_id
        WHERE datetime(h.checked_at) >= datetime('now', ?)
        GROUP BY h.source_id,s.name
        ORDER BY failures DESC,successes ASC,s.name ASC
        """,
        (f"-{safe_days} days",),
    ).fetchall()
    return {
        "days": safe_days,
        "items": [dict(row) for row in rows],
        "aggregate": [dict(row) for row in aggregate],
    }
