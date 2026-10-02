"""Daily pipeline orchestration with observable steps.

collect → classify → embed → cluster → label → trends → supply (embed/cluster products)
→ gate → competition → analyze (opportunities) → rescore → today → daily brief

Every step records counts in job_steps; failures in one step are recorded and the remaining steps run
where they still make sense (status 'partial').
"""

from __future__ import annotations

import json
import sqlite3
import traceback
import weakref
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from typing import Any

from ..analysis import classify_pending
from ..clustering import (
    cluster_pending_products,
    cluster_pending_signals,
    embed_pending_products,
    embed_pending_signals,
    label_clusters,
)
from ..core.config import PipelineConfig, get_pipeline_config
from ..core.ids import new_id
from ..core.logging import get_logger
from ..core.timeutil import day_key, iso, utcnow
from ..ingestion.runner import collect
from ..market import build_competition_profile
from ..opportunities import analyze_cluster, rescore, select_today
from ..providers.embeddings import get_embedder
from ..sources.base import BaseAdapter
from ..sources.registry import enabled_adapters
from ..studio.brief import build_brief
from ..studio.stories import assess_pending_stories
from ..trends import update_cluster_trends
from .brief import write_daily_brief
from .state import Heartbeat, current_owner

log = get_logger("jobs")


class JobRun:
    """Small helper that records a job and its steps."""

    def __init__(self, conn: sqlite3.Connection, job_type: str):
        self.conn = conn
        self.id = new_id()
        self.job_type = job_type
        self.stats: dict[str, Any] = {}
        self.failed_steps: list[str] = []
        now = iso(utcnow())
        conn.execute(
            "INSERT INTO jobs(id,job_type,started_at,status,heartbeat_at,owner) VALUES(?,?,?,'running',?,?)",
            (self.id, job_type, now, now, current_owner()),
        )
        conn.commit()
        self.heartbeat = Heartbeat(conn, self.id)
        # a JobRun dropped without finish() (unexpected crash path) must not look alive forever
        weakref.finalize(self, self.heartbeat.stop)

    def step(self, name: str, fn: Callable[[], Any], *, skip_if: bool = False, skip_reason: str = "") -> Any:
        started = iso(utcnow())
        cur = self.conn.execute(
            "INSERT INTO job_steps(job_id,step,started_at,status) VALUES(?,?,?,'running')",
            (self.id, name, started),
        )
        step_id = cur.lastrowid
        self.conn.commit()
        if skip_if:
            self.conn.execute(
                "UPDATE job_steps SET status='skipped', finished_at=?, counts_json=? WHERE id=?",
                (iso(utcnow()), json.dumps({"reason": skip_reason}), step_id),
            )
            self.conn.commit()
            self.stats[name] = {"skipped": skip_reason}
            return None
        try:
            result = fn()
            counts = _jsonable(result)
            self.conn.execute(
                "UPDATE job_steps SET status='success', finished_at=?, counts_json=? WHERE id=?",
                (iso(utcnow()), json.dumps(counts, ensure_ascii=False, default=str)[:20000], step_id),
            )
            self.conn.commit()
            self.stats[name] = counts
            log.info("step %s ok: %s", name, json.dumps(counts, default=str)[:300])
            return result
        except Exception as exc:  # recorded, pipeline continues
            self.conn.execute(
                "UPDATE job_steps SET status='failed', finished_at=?, error=? WHERE id=?",
                (iso(utcnow()), f"{exc}\n{traceback.format_exc()[-1500:]}", step_id),
            )
            self.conn.commit()
            self.failed_steps.append(name)
            self.stats[name] = {"error": str(exc)[:300]}
            log.exception("step %s failed", name)
            return None

    def finish(self, error: str | None = None) -> dict:
        self.heartbeat.stop()
        status = "failed" if error else "partial" if self.failed_steps else "success"
        self.conn.execute(
            "UPDATE jobs SET finished_at=?, status=?, stats_json=?, error=? WHERE id=?",
            (iso(utcnow()), status, json.dumps(self.stats, ensure_ascii=False, default=str), error, self.id),
        )
        self.conn.commit()
        return {"job_id": self.id, "status": status, "stats": self.stats, "failed_steps": self.failed_steps}


def _jsonable(value: Any) -> Any:
    if value is None:
        return {}
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return value


# ───────────────────────── gate ─────────────────────────


def gated_clusters(
    conn: sqlite3.Connection, cfg: PipelineConfig, *, limit: int | None = None, force: bool = False
) -> list[sqlite3.Row]:
    """Clusters worth an ANALYSIS call: enough independent evidence, and changed since last analysis."""
    rows = conn.execute(
        """SELECT pc.*, o.signal_count AS analysed_signal_count, o.version AS opp_version FROM pain_clusters pc
           LEFT JOIN opportunities o ON o.pain_cluster_id=pc.id
           WHERE pc.session_id IS NULL AND pc.signal_count>=? ORDER BY pc.velocity DESC, pc.signal_count DESC""",
        (cfg.gate_min_signals,),
    ).fetchall()
    out = []
    for r in rows:
        passes = (
            int(r["source_count"]) >= cfg.gate_min_sources
            or float(r["velocity"] or 0) >= cfg.gate_min_velocity
        )
        if not passes:
            continue
        if (
            not force
            and r["analysed_signal_count"] is not None
            and int(r["signal_count"]) < int(r["analysed_signal_count"]) + 3
            and r["analysis_status"] == "done"
        ):
            continue  # nothing new worth another model call
        out.append(r)
        if limit and len(out) >= limit:
            break
    return out


# ───────────────────────── daily pipeline ─────────────────────────


def run_daily(
    conn: sqlite3.Connection,
    *,
    adapters: list[BaseAdapter] | None = None,
    cfg: PipelineConfig | None = None,
    job_type: str = "daily",
    mock_only: bool = False,
    force_analyze: bool = False,
) -> dict:
    cfg = cfg or get_pipeline_config()
    job = JobRun(conn, job_type)
    embedder = get_embedder()
    try:
        if adapters is None:
            adapters = enabled_adapters(conn, mock_only=mock_only)
        supply_adapters = [a for a in adapters if a.type == "supply"]

        job.step("collect", lambda: collect(conn, adapters, max_workers=cfg.max_workers))
        job.step(
            "classify",
            lambda: classify_pending(conn, min_rule_score=cfg.rule_filter_min_score, job_id=job.id),
        )
        job.step(
            "embed",
            lambda: {
                "signals": embed_pending_signals(conn, embedder, min_relevance=cfg.classifier_min_relevance),
                "products": embed_pending_products(conn, embedder),
            },
        )
        job.step(
            "cluster",
            lambda: cluster_pending_signals(conn, embedder, threshold=cfg.cluster_threshold(embedder.name)),
        )
        job.step("label", lambda: {"labeled": label_clusters(conn, job_id=job.id)})
        job.step("trends", lambda: update_cluster_trends(conn))
        job.step(
            "solution_clusters",
            lambda: cluster_pending_products(
                conn, embedder, threshold=cfg.product_cluster_threshold(embedder.name)
            ),
        )

        gated = gated_clusters(conn, cfg, limit=cfg.max_clusters_analyzed_per_run, force=force_analyze)
        job.stats["gate"] = {"clusters": len(gated), "ids": [g["id"] for g in gated]}

        def competition() -> dict:
            done = 0
            for g in gated:
                if build_competition_profile(
                    conn,
                    embedder,
                    g["id"],
                    adapters=supply_adapters,
                    k=cfg.competitors_per_cluster,
                    job_id=job.id,
                ):
                    done += 1
            return {"profiles": done}

        job.step("competition", competition, skip_if=not gated, skip_reason="no cluster passed the gate")

        def analyze() -> dict:
            results: dict[str, Any] = {"ok": 0, "skipped": 0, "failed": 0, "opportunities": []}
            for g in gated:
                res = analyze_cluster(conn, g["id"], weights=cfg.weights, job_id=job.id)
                if res.get("ok"):
                    results["ok"] += 1
                    results["opportunities"].append({"id": res["opportunity_id"], "score": res["score"]})
                elif "not configured" in (res.get("reason") or ""):
                    results["skipped"] += 1
                    results["reason"] = res.get("reason")
                else:
                    results["failed"] += 1
            return results

        job.step("analyze", analyze, skip_if=not gated, skip_reason="no cluster passed the gate")

        def rescore_all() -> dict:
            ids = [
                r["id"]
                for r in conn.execute(
                    "SELECT id FROM opportunities WHERE session_id IS NULL AND status NOT IN ('archived')"
                )
            ]
            for oid in ids:
                rescore(conn, oid, weights=cfg.weights)
            return {"rescored": len(ids)}

        job.step("rescore", rescore_all)
        job.step(
            "today",
            lambda: {
                "picked": [
                    p["id"]
                    for p in select_today(
                        conn,
                        min_score=cfg.today_min_score,
                        min_confidence=cfg.today_min_confidence,
                        max_items=cfg.today_max_items,
                    )
                ]
            },
        )
        job.step("brief", lambda: {"report_id": write_daily_brief(conn, day_key(), job.stats)})
        job.step("stories", lambda: assess_pending_stories(conn, job_id=job.id))
        job.step("digest", lambda: build_brief(conn, day_key()))
    except Exception as exc:  # unexpected orchestration failure
        log.exception("pipeline crashed")
        return job.finish(error=str(exc))
    return job.finish()


def run_collect_only(conn: sqlite3.Connection, *, mock_only: bool = False) -> dict:
    cfg = get_pipeline_config()
    job = JobRun(conn, "collect")
    try:
        adapters = enabled_adapters(conn, mock_only=mock_only)
        job.step("collect", lambda: collect(conn, adapters, max_workers=cfg.max_workers))
    except Exception as exc:
        log.exception("collect crashed")
        return job.finish(error=str(exc))
    return job.finish()


def run_brief_refresh(conn: sqlite3.Connection, *, mock_only: bool = False) -> dict:
    """Refresh today's one-page brief: story sources only → assess → rebuild the page (statuses preserved)."""
    cfg = get_pipeline_config()
    job = JobRun(conn, "brief")
    try:
        adapters = [a for a in enabled_adapters(conn, mock_only=mock_only) if a.type == "story"]
        job.step("collect", lambda: collect(conn, adapters, max_workers=cfg.max_workers))
        job.step("stories", lambda: assess_pending_stories(conn, job_id=job.id))
        job.step("digest", lambda: build_brief(conn, day_key()))
    except Exception as exc:
        log.exception("brief refresh crashed")
        return job.finish(error=str(exc))
    return job.finish()
