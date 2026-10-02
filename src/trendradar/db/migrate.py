from __future__ import annotations

import re
import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_PATTERN = re.compile(r"^(\d{4})_.+\.sql$")


def available_migrations() -> list[tuple[int, Path]]:
    result = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        match = _PATTERN.match(path.name)
        if match:
            result.append((int(match.group(1)), path))
    return result


def schema_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def migrate(conn: sqlite3.Connection) -> list[int]:
    """Apply forward-only SQL migrations above the current PRAGMA user_version."""
    current = schema_version(conn)
    applied: list[int] = []
    for version, path in available_migrations():
        if version <= current:
            continue
        conn.executescript(path.read_text(encoding="utf-8"))
        conn.execute(f"PRAGMA user_version={version}")
        conn.commit()
        applied.append(version)
    return applied


def latest_version() -> int:
    versions = [v for v, _ in available_migrations()]
    return max(versions) if versions else 0
