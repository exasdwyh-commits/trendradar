"""Command line: trendradar init | seed-demo | daily | collect | brief | explore | ask | status | sources | serve | daemon"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .core.config import get_pipeline_config, sources_path
from .core.logging import setup_logging
from .core.settings import get_settings, reset_settings
from .db.connection import connect
from .db.migrate import migrate, schema_version


def _conn():
    settings = get_settings()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(settings.db_path)
    migrate(conn)
    return conn


def cmd_init(_: argparse.Namespace) -> int:
    conn = _conn()
    from .sources.registry import build_adapters, load_source_configs, sync_sources

    configs = load_source_configs(sources_path())
    sync_sources(conn, configs, build_adapters(configs))
    print(
        f"database ready at {get_settings().db_path} (schema v{schema_version(conn)}), {len(configs)} sources registered"
    )
    return 0


def cmd_seed(_: argparse.Namespace) -> int:
    from .jobs import seed_demo

    result = seed_demo(_conn())
    _print_job(result)
    return 0 if result["status"] in ("success", "partial") else 1


def cmd_daily(args: argparse.Namespace) -> int:
    from .jobs import run_daily

    result = run_daily(_conn(), mock_only=args.mock_only, force_analyze=args.force)
    _print_job(result)
    return 0 if result["status"] in ("success", "partial") else 1


def cmd_collect(args: argparse.Namespace) -> int:
    from .jobs import run_collect_only

    _print_job(run_collect_only(_conn(), mock_only=args.mock_only))
    return 0


def cmd_brief(args: argparse.Namespace) -> int:
    """Refresh (unless --no-fetch) and print today's 简报速览 in the terminal."""
    from .jobs import run_brief_refresh
    from .studio.brief import get_brief

    conn = _conn()
    if not args.no_fetch:
        _print_job(run_brief_refresh(conn, mock_only=args.mock_only))
    page = get_brief(conn, args.day)
    if args.json:
        print(json.dumps(page, indent=2, ensure_ascii=False, default=str))
        return 0
    print(f"简报 {page['day']} · 模式 {page['data_mode']}")
    titles = {"story": "今日值得写", "signal": "正在升温的用户痛点", "opportunity": "产品机会"}
    for section, items in page["sections"].items():
        if not items:
            continue
        print(f"\n== {titles[section]} ({len(items)}) ==")
        for it in items:
            src = it.get("source_name") or ""
            print(f"  [{int(it['score']):>3}] {it['title']}  ({it['origin']}{' · ' + src if src else ''})")
            if it.get("why"):
                print(f"        {it['why']}")
            if it.get("angles"):
                print(f"        切口: {' / '.join(it['angles'])}")
    return 0


def cmd_explore(args: argparse.Namespace) -> int:
    from .explore import run_explore
    from .sources.registry import build_adapters, load_source_configs

    adapters = build_adapters(load_source_configs(sources_path()))
    result = run_explore(_conn(), args.query, adapters=adapters, live=not args.mock_only)
    print(
        json.dumps(
            {
                k: result[k]
                for k in ("session_id", "data_mode", "overview", "gaps", "opportunity_draft", "warnings")
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )
    for c in result["clusters"]:
        print(f"- [{c['coverage']}] {c['label']} ({c['signal_count']} signals, relevance {c['relevance']})")
    for p in result["products"]:
        print(f"  · {p['name']} — {p['tagline']} ({p['origin']})")
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    from .ask import ask

    result = ask(_conn(), args.question)
    print(result["answer_md"])
    print(
        "\ncitations:",
        ", ".join(result["citations"]) or "none",
        f"(generated_by={result['generated_by']}, data_mode={result['data_mode']})",
    )
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    from .providers.classifier import classifier_status
    from .providers.embeddings import embedding_status
    from .providers.llm import slot_status

    conn = _conn()
    print(f"db: {get_settings().db_path} (schema v{schema_version(conn)})")
    for t in ("signals", "pain_clusters", "products", "opportunities", "jobs"):
        print(f"  {t:14s} {conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]}")
    print("models:")
    for slot, st in slot_status().items():
        print(
            f"  {slot:16s} {'configured (' + str(st['model']) + ')' if st['enabled'] else 'not configured'}"
        )
    print("embedding:", embedding_status())
    print("classifier:", classifier_status())
    last = conn.execute(
        "SELECT job_type, status, started_at FROM jobs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    print("last job:", dict(last) if last else None)
    return 0


def cmd_sources(args: argparse.Namespace) -> int:
    from .sources.registry import build_adapters, load_source_configs

    adapters = build_adapters(load_source_configs(sources_path()), only_enabled=False)
    for a in adapters:
        if args.test:
            h = a.health()
            print(f"{a.id:16s} {a.type:7s} {h.mode:5s} {'ok ' if h.ok else 'ERR'} {h.detail}")
        else:
            print(f"{a.id:16s} {a.type:7s} {a.mode:5s} {'enabled' if a.config.enabled else 'disabled'}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    # CLI overrides must reach the app's security config (and reload workers, which inherit env).
    if args.host:
        os.environ["HOST"] = args.host
    if args.port:
        os.environ["PORT"] = str(args.port)
    reset_settings()
    settings = get_settings()
    if args.scheduler:
        from .jobs.scheduler import start_background

        start_background()
    uvicorn.run(
        "trendradar.web:app",
        host=args.host or settings.host,
        port=args.port or settings.port,
        reload=args.reload,
        log_level=settings.log_level.lower(),
    )
    return 0


def cmd_daemon(_: argparse.Namespace) -> int:
    from .jobs.scheduler import run_forever

    _conn().close()
    run_forever()
    return 0


def _print_job(result: dict) -> None:
    print(f"job {result['job_id']}: {result['status']}")
    for step, counts in result["stats"].items():
        print(f"  {step:18s} {json.dumps(counts, ensure_ascii=False, default=str)[:160]}")
    if result.get("failed_steps"):
        print("failed steps:", ", ".join(result["failed_steps"]))


def main(argv: list[str] | None = None) -> int:
    setup_logging(get_settings().log_level)
    parser = argparse.ArgumentParser(
        prog="trendradar", description=f"{get_pipeline_config().app_name} — AI business opportunity radar"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create/migrate the database and register sources").set_defaults(fn=cmd_init)
    sub.add_parser("seed-demo", help="run the pipeline on demo fixtures (no API keys needed)").set_defaults(
        fn=cmd_seed
    )
    p = sub.add_parser("daily", help="run the daily pipeline")
    p.add_argument("--mock-only", action="store_true")
    p.add_argument("--force", action="store_true", help="re-analyse gated clusters even without new signals")
    p.set_defaults(fn=cmd_daily)
    p = sub.add_parser("collect", help="collect only")
    p.add_argument("--mock-only", action="store_true")
    p.set_defaults(fn=cmd_collect)
    p = sub.add_parser("brief", help="refresh and print today's brief (简报速览)")
    p.add_argument("--mock-only", action="store_true")
    p.add_argument("--no-fetch", action="store_true", help="print the stored brief without collecting")
    p.add_argument("--day", default=None, help="YYYY-MM-DD (default: today)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_brief)
    p = sub.add_parser("explore", help="query → market map")
    p.add_argument("query")
    p.add_argument("--mock-only", action="store_true")
    p.set_defaults(fn=cmd_explore)
    p = sub.add_parser("ask", help="ask a question answered from the database")
    p.add_argument("question")
    p.set_defaults(fn=cmd_ask)
    sub.add_parser("status", help="show database and provider status").set_defaults(fn=cmd_status)
    p = sub.add_parser("sources", help="list sources")
    p.add_argument("--test", action="store_true", help="run health checks")
    p.set_defaults(fn=cmd_sources)
    p = sub.add_parser("serve", help="run the web app")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("--reload", action="store_true")
    p.add_argument("--scheduler", action="store_true", help="also run the daily scheduler in-process")
    p.set_defaults(fn=cmd_serve)
    sub.add_parser("daemon", help="run the daily scheduler only").set_defaults(fn=cmd_daemon)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
