from __future__ import annotations

import argparse
import json
from pathlib import Path

import uvicorn

from .brief import write_daily_brief
from .config import enabled_sources, load_sources, load_yaml
from .db import connect, init_db
from .exporter import export_markdown, export_wechat_html
from .pipeline import run_daily, sync_sources, today
from .scheduler import daemon
from .trends import world_model_update
from .web import create_app


def resolve(root: Path):
    settings = load_yaml(root / "config" / "settings.yml")
    sources = load_sources(root / "config" / "sources.yml")
    db_path = root / "data" / "trendradar.db"
    conn = connect(db_path)
    init_db(conn, root / "schema.sql")
    sync_sources(conn, sources)
    return settings, sources, conn


def main() -> None:
    parser = argparse.ArgumentParser(prog="trendradar")
    parser.add_argument(
        "command",
        choices=["init","daily","status","serve","daemon","world-model","brief","export-md","export-wechat"],
    )
    parser.add_argument("target", nargs="?")
    parser.add_argument("--root", default=".")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    settings, sources, conn = resolve(root)

    def tick():
        cfg = settings.get("collection",{})
        ranking = settings.get("ranking",{})
        return run_daily(
            conn,
            enabled_sources(sources),
            timeout=float(cfg.get("request_timeout_seconds",18)),
            limit=int(cfg.get("per_source_limit",18)),
            enrich_limit=int(cfg.get("article_enrich_limit",6)),
            output_dir=root / "output" / "daily",
            fast_limit=int(ranking.get("fast_pool_size",40)),
            cognition_limit=int(ranking.get("cognition_pool_size",12)),
            candidate_snapshot_limit=int(ranking.get("candidate_snapshot_size",20)),
            lookback_hours=int(cfg.get("lookback_hours",72)),
            collection_workers=int(cfg.get("max_workers",6)),
        )

    if args.command == "init":
        print(json.dumps({
            "ok": True,
            "product": settings.get("app",{}).get("name"),
            "enabled_sources": len(enabled_sources(sources)),
        }, ensure_ascii=False, indent=2))
        return

    if args.command == "daily":
        print(json.dumps(tick(), ensure_ascii=False, indent=2))
        return

    if args.command == "world-model":
        print(json.dumps(world_model_update(conn), ensure_ascii=False, indent=2))
        return

    if args.command == "brief":
        print(write_daily_brief(conn, root / "output" / "daily"))
        return

    if args.command == "status":
        counts = {}
        for table in ["sources","intelligence","story_clusters","candidates","trends","research","theses","articles"]:
            counts[table] = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        counts["today"] = today(conn, 3)
        print(json.dumps(counts, ensure_ascii=False, indent=2))
        return

    if args.command == "serve":
        uvicorn.run(create_app(root), host="127.0.0.1", port=args.port)
        return

    if args.command == "daemon":
        app_cfg = settings.get("app",{})
        daemon(
            tick,
            conn,
            timezone_name=app_cfg.get("timezone","Asia/Shanghai"),
            hour=int(app_cfg.get("daily_hour",13)),
        )
        return

    if args.command in {"export-md","export-wechat"}:
        if not args.target:
            raise SystemExit("article id required")
        fn = export_markdown if args.command == "export-md" else export_wechat_html
        print(fn(conn, args.target, root / "output"))
        return


if __name__ == "__main__":
    main()
