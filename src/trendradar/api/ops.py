from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..db import schema_version
from ..evaluation import (
    calibration_summary,
    evaluation_summary,
    latest_blind_round,
    submit_blind_round,
)
from ..llm import slot_status


class BlindSubmitBody(BaseModel):
    picks: list[str]


def build_ops_router(get_conn) -> APIRouter:
    router=APIRouter()

    @router.get("/api/health")
    def health(conn: sqlite3.Connection = Depends(get_conn)):
        last=conn.execute(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return {
            "ok":True,
            "schema_version":schema_version(conn),
            "last_run":dict(last) if last else None,
            "models":slot_status(),
        }

    @router.get("/api/blind/latest")
    def blind_latest(conn: sqlite3.Connection = Depends(get_conn)):
        return {
            "round":latest_blind_round(conn),
            "summary":evaluation_summary(conn),
            "calibration":calibration_summary(conn),
        }

    @router.post("/api/blind/{round_id}/submit")
    def blind_submit(round_id: str, body: BlindSubmitBody, conn: sqlite3.Connection = Depends(get_conn)):
        try:
            return {
                "round":submit_blind_round(conn,round_id,body.picks),
                "summary":evaluation_summary(conn),
                "calibration":calibration_summary(conn),
            }
        except Exception as exc:
            raise HTTPException(400,str(exc)) from exc

    @router.get("/api/evaluation")
    def evaluation(conn: sqlite3.Connection = Depends(get_conn)):
        return {
            "summary":evaluation_summary(conn),
            "calibration":calibration_summary(conn),
        }

    @router.get("/api/ai-runs")
    def ai_runs(limit: int = 100, conn: sqlite3.Connection = Depends(get_conn)):
        rows=conn.execute(
            """
            SELECT * FROM ai_runs
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1,min(limit,300)),),
        ).fetchall()
        aggregate=conn.execute(
            """
            SELECT slot,task,
              COUNT(*) calls,
              SUM(ok) ok_calls,
              SUM(input_tokens) input_tokens,
              SUM(output_tokens) output_tokens,
              ROUND(SUM(cost),6) cost_cny,
              SUM(retries) retries,
              ROUND(AVG(duration_ms),1) avg_duration_ms
            FROM ai_runs
            GROUP BY slot,task
            ORDER BY calls DESC
            """
        ).fetchall()
        return {
            "items":[dict(r) for r in rows],
            "aggregate":[dict(r) for r in aggregate],
        }

    @router.get("/api/source-yield")
    def source_yield(conn: sqlite3.Connection = Depends(get_conn)):
        rows=conn.execute(
            """
            SELECT s.id,s.name,s.role,s.tier,s.reliability,s.business_value,s.noise,s.accuracy,
              COUNT(DISTINCT i.id) intelligence_count,
              COUNT(DISTINCT c.id) candidate_count,
              COUNT(DISTINCT CASE WHEN c.action='WRITE' THEN c.id END) write_count,
              COUNT(DISTINCT CASE WHEN cri.content_rank<=3 THEN cri.run_id || ':' || c.id END) top3_count
            FROM sources s
            LEFT JOIN intelligence i ON i.source_id=s.id
            LEFT JOIN cluster_items ci ON ci.intelligence_id=i.id
            LEFT JOIN candidates c ON c.cluster_id=ci.cluster_id
            LEFT JOIN candidate_run_items cri ON cri.candidate_id=c.id
            GROUP BY s.id
            ORDER BY s.tier ASC,top3_count DESC,candidate_count DESC,s.name ASC
            """
        ).fetchall()
        items=[]
        for row in rows:
            item=dict(row)
            total=item["intelligence_count"] or 0
            item["candidate_yield"]=round(item["candidate_count"]/total,4) if total else None
            item["write_yield"]=round(item["write_count"]/total,4) if total else None
            items.append(item)
        return {"items":items}

    @router.get("/api/sources")
    def sources(conn: sqlite3.Connection = Depends(get_conn)):
        rows=conn.execute(
            """
            SELECT s.*,h.last_attempt_at,h.last_success_at,h.last_error,
              h.consecutive_failures,h.last_item_count,h.latency_ms
            FROM sources s LEFT JOIN source_health h ON h.source_id=s.id
            ORDER BY s.role,s.lane,s.name
            """
        ).fetchall()
        return {"items":[dict(r) for r in rows]}

    return router
