"""FastAPI application: typed JSON API + static frontend."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__
from ..ask import ask as run_ask
from ..core.config import get_pipeline_config, sources_path
from ..core.errors import NotFound, RadarError, ValidationFailed
from ..core.logging import get_logger
from ..core.settings import get_settings
from ..db.connection import connect
from ..db.migrate import migrate, schema_version
from ..explore import load_explore, run_explore
from ..jobs import run_brief_refresh, run_collect_only, run_daily, seed_demo
from ..jobs.state import active_job, is_interrupted, recover_interrupted
from ..opportunities import STATUSES, allowed_transitions, generate_brief, get_brief, set_status
from ..providers.classifier import classifier_status
from ..providers.embeddings import embedding_status
from ..providers.llm import rolling_24h_usage, slot_status
from ..sources.registry import build_adapters, enabled_adapters, load_source_configs, sync_sources
from . import queries
from .security import install_security
from .studio import build_router as build_studio_router

log = get_logger("api")


# ───────────────────────── dependencies ─────────────────────────


def get_conn() -> Iterator[sqlite3.Connection]:
    settings = get_settings()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


_job_lock = threading.Lock()
# Accepted-but-not-yet-recorded job of *this* process; the durable truth is jobs/state.active_job().
_running_job: dict[str, str | None] = {"type": None, "started_at": None}


def _running_state(conn: sqlite3.Connection) -> dict[str, str | None]:
    with _job_lock:
        if _running_job["type"]:
            return dict(_running_job)
    job = active_job(conn)
    return (
        {"type": job["type"], "started_at": job["started_at"]} if job else {"type": None, "started_at": None}
    )


def _run_in_background(job_type: str, fn) -> None:
    def target():
        settings = get_settings()
        conn = connect(settings.db_path)
        try:
            fn(conn)
        except Exception:
            log.exception("background job %s failed", job_type)
        finally:
            conn.close()
            with _job_lock:
                _running_job["type"] = None
                _running_job["started_at"] = None

    threading.Thread(target=target, name=f"job-{job_type}", daemon=True).start()


# ───────────────────────── schemas ─────────────────────────


class StatusChange(BaseModel):
    status: Literal[
        "discovered", "watching", "promising", "researching", "validated", "building", "rejected", "archived"
    ]
    note: str | None = Field(default=None, max_length=500)


class ExploreRequest(BaseModel):
    query: str = Field(min_length=2, max_length=200)
    live: bool = True


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class JobRequest(BaseModel):
    type: Literal["daily", "collect", "seed", "brief"] = "daily"
    mock_only: bool = False


class SourceToggle(BaseModel):
    enabled: bool


# ───────────────────────── app ─────────────────────────


def _prepare_database() -> None:
    settings = get_settings()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(settings.db_path)
    try:
        migrate(conn)
        recovered = recover_interrupted(conn)
        if recovered:
            log.warning("marked %d interrupted job(s) from a previous run", recovered)
        configs = load_source_configs(sources_path())
        sync_sources(conn, configs, build_adapters(configs))
    finally:
        conn.close()


@asynccontextmanager
async def _lifespan(_: FastAPI):
    _prepare_database()
    yield


def create_app(static_dir: Path | None = None) -> FastAPI:
    app = FastAPI(
        title="TrendRadar 写作台",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=_lifespan,
    )
    install_security(app, get_settings())

    @app.exception_handler(RadarError)
    async def radar_error(_: Request, exc: RadarError):
        return JSONResponse(status_code=exc.status, content=exc.to_dict())

    # ── health / settings ──
    @app.get("/api/health")
    def health(conn: sqlite3.Connection = Depends(get_conn)):
        cfg = get_pipeline_config()
        counts = {
            "signals": conn.execute("SELECT COUNT(*) FROM signals WHERE dedup_of IS NULL").fetchone()[0],
            "pain_clusters": conn.execute(
                "SELECT COUNT(*) FROM pain_clusters WHERE session_id IS NULL"
            ).fetchone()[0],
            "products": conn.execute("SELECT COUNT(*) FROM products WHERE alias_of IS NULL").fetchone()[0],
            "opportunities": conn.execute(
                "SELECT COUNT(*) FROM opportunities WHERE session_id IS NULL AND status NOT IN ('archived')"
            ).fetchone()[0],
            "documents": conn.execute("SELECT COUNT(*) FROM documents WHERE status!='archived'").fetchone()[
                0
            ],
            "materials": conn.execute("SELECT COUNT(*) FROM materials WHERE archived=0").fetchone()[0],
            "brief_new": conn.execute(
                "SELECT COUNT(*) FROM brief_items WHERE status='new' AND day=(SELECT MAX(day) FROM brief_items)"
            ).fetchone()[0],
        }
        return {
            "ok": True,
            "version": __version__,
            "schema_version": schema_version(conn),
            "app_name": cfg.app_name,
            "counts": counts,
            "providers": {
                "llm": slot_status(),
                "embedding": embedding_status(),
                "classifier": classifier_status(),
            },
            "running_job": _running_state(conn),
        }

    @app.get("/api/settings")
    def settings_view(conn: sqlite3.Connection = Depends(get_conn)):
        s = get_settings()
        cfg = get_pipeline_config()
        usage = {
            slot: rolling_24h_usage(conn, slot)
            for slot in ("FAST_MODEL", "ANALYSIS_MODEL", "EMBEDDING_MODEL")
        }
        by_task = [
            dict(r)
            for r in conn.execute(
                "SELECT task, model, COUNT(*) calls, SUM(input_tokens) input_tokens, SUM(output_tokens) output_tokens, ROUND(SUM(cost),4) cost, SUM(ok=0) failures FROM ai_runs WHERE run_at >= datetime('now','-7 days') GROUP BY task, model ORDER BY calls DESC"
            )
        ]
        return {
            "models": slot_status(),
            "embedding": embedding_status(),
            "classifier": classifier_status(),
            "producthunt_mode": s.producthunt_mode,
            "producthunt_token_set": bool(s.producthunt_token),
            "github_token_set": bool(s.github_token),
            "timezone": s.timezone,
            "daily_hour": s.daily_hour,
            "budget_cny_24h": s.ai_24h_budget_cny,
            "usage_24h": usage,
            "usage_7d_by_task": by_task,
            "pipeline": {
                k: getattr(cfg, k)
                for k in (
                    "rule_filter_min_score",
                    "classifier_min_relevance",
                    "cluster_threshold_api",
                    "cluster_threshold_local",
                    "gate_min_signals",
                    "gate_min_sources",
                    "gate_min_velocity",
                    "max_clusters_analyzed_per_run",
                    "competitors_per_cluster",
                    "today_min_score",
                    "today_min_confidence",
                    "today_max_items",
                )
            },
            "weights": cfg.weights,
            "db_path": str(s.db_path),
            "config_dir": str(sources_path().parent),
        }

    # ── today / radar ──
    @app.get("/api/today")
    def today(conn: sqlite3.Connection = Depends(get_conn)):
        cfg = get_pipeline_config()
        return queries.today_payload(
            conn, min_score=cfg.today_min_score, min_confidence=cfg.today_min_confidence
        )

    @app.get("/api/radar")
    def radar(window: Literal["7d", "30d", "90d"] = "30d", conn: sqlite3.Connection = Depends(get_conn)):
        return queries.radar_payload(conn, {"7d": 7, "30d": 30, "90d": 90}[window])

    # ── opportunities ──
    @app.get("/api/opportunities")
    def opportunities(
        status: str | None = None,
        persona: str | None = None,
        category: str | None = None,
        min_score: float | None = None,
        q: str | None = None,
        data_mode: str | None = None,
        sort: str = "opportunity_score",
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        statuses = [s for s in (status or "").split(",") if s] or None
        if statuses and any(s not in STATUSES for s in statuses):
            raise ValidationFailed("unknown status filter", details={"allowed": STATUSES})
        items, total = queries.list_opportunities(
            conn,
            status=statuses,
            persona=persona,
            category=category,
            min_score=min_score,
            q=q,
            sort=sort,
            limit=limit,
            offset=offset,
            data_mode=data_mode,
        )
        facets = {
            "status": [
                dict(r)
                for r in conn.execute(
                    "SELECT status value, COUNT(*) n FROM opportunities WHERE session_id IS NULL GROUP BY status"
                )
            ],
            "persona": [
                dict(r)
                for r in conn.execute(
                    "SELECT pc.persona value, COUNT(*) n FROM opportunities o JOIN pain_clusters pc ON pc.id=o.pain_cluster_id WHERE o.session_id IS NULL GROUP BY pc.persona"
                )
            ],
            "category": [
                dict(r)
                for r in conn.execute(
                    "SELECT pc.category value, COUNT(*) n FROM opportunities o JOIN pain_clusters pc ON pc.id=o.pain_cluster_id WHERE o.session_id IS NULL GROUP BY pc.category"
                )
            ],
        }
        return {"items": items, "total": total, "facets": facets}

    @app.get("/api/opportunities/{opportunity_id}")
    def opportunity(opportunity_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        d = queries.get_opportunity(conn, opportunity_id)
        if d is None:
            raise NotFound("opportunity not found", details={"id": opportunity_id})
        d["allowed_transitions"] = sorted(allowed_transitions(d["status"]))
        return d

    @app.post("/api/opportunities/{opportunity_id}/status")
    def change_status(opportunity_id: str, body: StatusChange, conn: sqlite3.Connection = Depends(get_conn)):
        return set_status(conn, opportunity_id, body.status, note=body.note)

    @app.get("/api/opportunities/{opportunity_id}/brief")
    def brief(opportunity_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        b = get_brief(conn, opportunity_id)
        if b is None:
            raise NotFound("no brief yet", details={"id": opportunity_id})
        return b

    @app.post("/api/opportunities/{opportunity_id}/brief")
    def make_brief(opportunity_id: str, force: bool = False, conn: sqlite3.Connection = Depends(get_conn)):
        return generate_brief(conn, opportunity_id, force=force)

    # ── clusters / signals / products ──
    @app.get("/api/clusters/{cluster_id}")
    def cluster(cluster_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        d = queries.cluster_detail(conn, cluster_id)
        if d is None:
            raise NotFound("cluster not found", details={"id": cluster_id})
        return d

    @app.get("/api/signals/{signal_id}")
    def signal(signal_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        d = queries.signal_detail(conn, signal_id)
        if d is None:
            raise NotFound("signal not found", details={"id": signal_id})
        return d

    @app.get("/api/products")
    def products(
        q: str | None = None,
        origin: str | None = None,
        limit: int = Query(50, ge=1, le=200),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        where, params = ["alias_of IS NULL"], []
        if q:
            where.append("(name LIKE ? OR tagline LIKE ?)")
            params += [f"%{q}%", f"%{q}%"]
        if origin:
            where.append("origin=?")
            params.append(origin)
        rows = conn.execute(
            f"SELECT id, source_id, name, tagline, url, website, votes, comments, rating, review_count, launched_at, pricing, pricing_origin, origin, categories_json FROM products WHERE {' AND '.join(where)} ORDER BY votes DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        items = []
        for r in rows:
            d = dict(r)
            d["categories"] = json.loads(d.pop("categories_json") or "[]")
            items.append(d)
        clusters = [
            dict(r)
            for r in conn.execute(
                "SELECT id, label, product_count, new_90d, avg_rating, total_votes, maturity, data_mode FROM product_clusters ORDER BY product_count DESC LIMIT 50"
            )
        ]
        return {"items": items, "clusters": clusters}

    @app.get("/api/products/{product_id}")
    def product(product_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        d = queries.product_detail(conn, product_id)
        if d is None:
            raise NotFound("product not found", details={"id": product_id})
        return d

    # ── explore / ask ──
    @app.post("/api/explore")
    def explore(body: ExploreRequest, conn: sqlite3.Connection = Depends(get_conn)):
        adapters = enabled_adapters(conn)
        return run_explore(conn, body.query.strip(), adapters=adapters, live=body.live)

    @app.get("/api/explore/{session_id}")
    def explore_session(session_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        d = load_explore(conn, session_id)
        if d is None:
            raise NotFound("explore session not found", details={"id": session_id})
        return d

    @app.get("/api/explore")
    def explore_history(conn: sqlite3.Connection = Depends(get_conn)):
        return {
            "items": [
                dict(r)
                for r in conn.execute(
                    "SELECT id, query, status, created_at FROM explore_sessions ORDER BY created_at DESC LIMIT 20"
                )
            ]
        }

    @app.post("/api/ask")
    def ask_endpoint(body: AskRequest, conn: sqlite3.Connection = Depends(get_conn)):
        return run_ask(conn, body.question.strip())

    @app.get("/api/ask")
    def ask_history(conn: sqlite3.Connection = Depends(get_conn)):
        return {
            "items": [
                {**dict(r), "citations": json.loads(r["citations_json"] or "[]")}
                for r in conn.execute(
                    "SELECT id, question, answer_md, citations_json, generated_by, created_at FROM ask_sessions ORDER BY created_at DESC LIMIT 20"
                )
            ]
        }

    # ── sources ──
    @app.get("/api/sources")
    def sources(conn: sqlite3.Connection = Depends(get_conn)):
        rows = conn.execute(
            "SELECT s.*, h.last_attempt_at, h.last_success_at, h.last_error, h.consecutive_failures, h.last_item_count, h.latency_ms FROM sources s LEFT JOIN source_health h ON h.source_id=s.id ORDER BY s.kind, s.mode, s.id"
        ).fetchall()
        counts = {
            r["source_id"]: dict(r)
            for r in conn.execute(
                "SELECT source_id, COUNT(*) signals, SUM(created_at >= datetime('now','-7 days')) last_7d FROM signals WHERE dedup_of IS NULL GROUP BY source_id"
            )
        }
        pcounts = {
            r["source_id"]: r["n"]
            for r in conn.execute("SELECT source_id, COUNT(*) n FROM products GROUP BY source_id")
        }
        items = []
        for r in rows:
            d = dict(r)
            d["config"] = json.loads(d.pop("config_json") or "{}")
            d["signals"] = counts.get(r["id"], {}).get("signals", 0)
            d["signals_7d"] = counts.get(r["id"], {}).get("last_7d", 0) or 0
            d["products"] = pcounts.get(r["id"], 0)
            items.append(d)
        return {"items": items}

    @app.post("/api/sources/{source_id}/test")
    def test_source(source_id: str):
        configs = {c.id: c for c in load_source_configs(sources_path())}
        if source_id not in configs:
            raise NotFound("source not found", details={"id": source_id})
        adapter = build_adapters([configs[source_id]], only_enabled=False)[0]
        h = adapter.health()
        return {"id": source_id, "ok": h.ok, "mode": h.mode, "detail": h.detail}

    @app.post("/api/sources/{source_id}/toggle")
    def toggle_source(source_id: str, body: SourceToggle, conn: sqlite3.Connection = Depends(get_conn)):
        if conn.execute("SELECT 1 FROM sources WHERE id=?", (source_id,)).fetchone() is None:
            raise NotFound("source not found", details={"id": source_id})
        conn.execute(
            "UPDATE sources SET enabled=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            (1 if body.enabled else 0, source_id),
        )
        conn.commit()
        return {"id": source_id, "enabled": body.enabled}

    # ── jobs ──
    @app.get("/api/jobs")
    def jobs(limit: int = Query(20, ge=1, le=100), conn: sqlite3.Connection = Depends(get_conn)):
        rows = conn.execute("SELECT * FROM jobs ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
        items = []
        for r in rows:
            d = dict(r)
            d["stats"] = json.loads(d.pop("stats_json") or "{}")
            d["interrupted"] = is_interrupted(d.get("error"))
            d["steps"] = [
                {**dict(s), "counts": json.loads(s["counts_json"] or "{}")}
                for s in conn.execute(
                    "SELECT step, status, started_at, finished_at, counts_json, error FROM job_steps WHERE job_id=? ORDER BY id",
                    (r["id"],),
                )
            ]
            for s in d["steps"]:
                s.pop("counts_json", None)
            d["ai_calls"] = conn.execute(
                "SELECT COUNT(*) FROM ai_runs WHERE job_id=?", (r["id"],)
            ).fetchone()[0]
            items.append(d)
        return {"items": items, "running": _running_state(conn)}

    @app.post("/api/jobs/run", status_code=202)
    def run_job(body: JobRequest, conn: sqlite3.Connection = Depends(get_conn)):
        busy = _running_state(conn)
        with _job_lock:
            if busy["type"] or _running_job["type"]:
                running_type = _running_job["type"] or busy["type"]
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "job_running",
                        "message": f"a {running_type} job is already running",
                    },
                )
            from ..core.timeutil import iso, utcnow

            _running_job["type"] = body.type
            _running_job["started_at"] = iso(utcnow())
        if body.type == "seed":
            _run_in_background("seed", seed_demo)
        elif body.type == "collect":
            _run_in_background("collect", lambda c: run_collect_only(c, mock_only=body.mock_only))
        elif body.type == "brief":
            _run_in_background("brief", lambda c: run_brief_refresh(c, mock_only=body.mock_only))
        else:
            _run_in_background("daily", lambda c: run_daily(c, mock_only=body.mock_only))
        return {"accepted": True, "type": body.type}

    @app.get("/api/reports")
    def reports(conn: sqlite3.Connection = Depends(get_conn)):
        return {
            "items": [
                dict(r)
                for r in conn.execute(
                    "SELECT id, day, kind, content_md, created_at FROM reports ORDER BY day DESC LIMIT 30"
                )
            ]
        }

    app.include_router(build_studio_router(get_conn))

    # ── static frontend ──
    static_dir = static_dir or (Path(__file__).resolve().parents[3] / "frontend" / "dist")
    if static_dir.exists():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            candidate = static_dir / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(static_dir / "index.html")
    else:

        @app.get("/", include_in_schema=False)
        def no_frontend():
            return JSONResponse(
                {
                    "message": "Frontend not built. Run `make web-build` (or `cd frontend && npm run build`) — API docs at /api/docs."
                }
            )

    return app
