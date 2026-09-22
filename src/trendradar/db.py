from __future__ import annotations

import sqlite3
from pathlib import Path

CURRENT_SCHEMA_VERSION = 5


def connect(path: str | Path) -> sqlite3.Connection:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if column not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def migrate(conn: sqlite3.Connection) -> None:
    """
    Forward-only compatibility for local SQLite files.

    TrendRadar has a single product line, but a user's local database may survive
    many code updates. New columns must therefore be added explicitly instead of
    relying on CREATE TABLE IF NOT EXISTS, which never mutates an existing table.
    """
    _ensure_column(conn, "sources", "tier", "INTEGER NOT NULL DEFAULT 3")
    _ensure_column(conn, "sources", "reliability", "INTEGER NOT NULL DEFAULT 70")
    _ensure_column(conn, "sources", "business_value", "INTEGER NOT NULL DEFAULT 65")
    _ensure_column(conn, "sources", "noise", "INTEGER NOT NULL DEFAULT 30")
    _ensure_column(conn, "sources", "accuracy", "INTEGER NOT NULL DEFAULT 70")
    _ensure_column(conn, "sources", "window_days", "INTEGER")
    _ensure_column(conn, "sources", "scan_limit", "INTEGER")
    _ensure_column(conn, "sources", "max_per_round", "INTEGER")
    _ensure_column(conn, "blind_rounds", "candidate_run_id", "TEXT REFERENCES candidate_runs(id) ON DELETE SET NULL")
    _ensure_column(conn, "media_assets", "evidence_ids_json", "TEXT NOT NULL DEFAULT '[]'")
    conn.execute(f"PRAGMA user_version={CURRENT_SCHEMA_VERSION}")
    conn.commit()


def init_db(conn: sqlite3.Connection, schema_path: str | Path) -> None:
    conn.executescript(Path(schema_path).read_text(encoding="utf-8"))
    migrate(conn)
    conn.commit()



def schema_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])
