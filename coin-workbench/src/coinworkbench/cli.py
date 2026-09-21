from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import enabled_sources, load_sources
from .db import connect, init_db
from .pipeline import collect_all, sync_sources


def paths(root: Path) -> tuple[Path, Path, Path]:
    return (
        root / "config" / "sources.yml",
        root / "schema.sql",
        root / "data" / "coin-workbench.db",
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="coin-workbench")
    parser.add_argument("command", choices=["init", "collect", "status"])
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--db", default=None)
    args = parser.parse_args()

    root = Path(args.root)
    source_path, schema_path, default_db = paths(root)
    conn = connect(args.db or default_db)
    init_db(conn, schema_path)
    sources = load_sources(source_path)
    sync_sources(conn, sources)

    if args.command == "init":
        print(json.dumps({"ok": True, "sources": len(sources)}, ensure_ascii=False))
        return

    if args.command == "collect":
        stats = collect_all(conn, enabled_sources(sources))
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return

    row = conn.execute("SELECT COUNT(*) AS n FROM intelligence").fetchone()
    by_lane = conn.execute(
        "SELECT lane, COUNT(*) AS n FROM intelligence GROUP BY lane ORDER BY n DESC"
    ).fetchall()
    print(json.dumps({
        "intelligence": row["n"],
        "by_lane": {r["lane"]: r["n"] for r in by_lane},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
