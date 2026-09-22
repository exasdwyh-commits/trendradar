from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..pipeline import today
from ..trends import latest_world_model_update
from ..writing import (
    article_detail,
    challenge_article,
    confirm_thesis,
    draft_article,
    hold_thesis,
    latest_research,
    propose_thesis,
    research_candidate,
)


class ConfirmBody(BaseModel):
    horizon: str = "12个月"


def _json_fields(data: dict, fields: list[str]) -> dict:
    for field in fields:
        if field in data and isinstance(data[field], str):
            try:
                data[field] = json.loads(data[field] or "[]")
            except json.JSONDecodeError:
                pass
    return data


def build_editorial_router(get_conn) -> APIRouter:
    router=APIRouter()

    @router.get("/api/dashboard")
    def dashboard(conn: sqlite3.Connection = Depends(get_conn)):
        pending = conn.execute(
            """
            SELECT t.*,c.title candidate_title
            FROM theses t JOIN candidates c ON c.id=t.candidate_id
            WHERE t.status='PENDING' ORDER BY t.created_at DESC LIMIT 5
            """
        ).fetchall()
        return {
            "today": today(conn, 3),
            "pending_decisions": [dict(x) for x in pending],
            "world_model": latest_world_model_update(conn),
        }

    @router.get("/api/today")
    def get_today(limit: int = 3, conn: sqlite3.Connection = Depends(get_conn)):
        return {"items": today(conn, max(1,min(limit,5)))}

    @router.get("/api/candidates")
    def candidates(limit: int = 30, conn: sqlite3.Connection = Depends(get_conn)):
        rows=conn.execute(
            "SELECT * FROM candidates ORDER BY updated_at DESC,content_score DESC LIMIT ?",
            (max(1,min(limit,100)),),
        ).fetchall()
        return {"items":[dict(r) for r in rows]}

    @router.get("/api/candidates/{candidate_id}")
    def candidate(candidate_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        row=conn.execute("SELECT * FROM candidates WHERE id=?",(candidate_id,)).fetchone()
        if not row:
            raise HTTPException(404,"candidate not found")
        evidence=conn.execute(
            """
            SELECT i.* FROM cluster_items ci JOIN intelligence i ON i.id=ci.intelligence_id
            WHERE ci.cluster_id=? ORDER BY i.evidence_score DESC
            """,
            (row["cluster_id"],),
        ).fetchall()
        return {
            "candidate":dict(row),
            "evidence":[dict(x) for x in evidence],
            "research":latest_research(conn,candidate_id),
        }

    @router.post("/api/candidates/{candidate_id}/research")
    def start_research(candidate_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        try:
            return {"ok":True,"research_id":research_candidate(conn,candidate_id)}
        except Exception as exc:
            raise HTTPException(400,str(exc)) from exc

    @router.post("/api/candidates/{candidate_id}/thesis")
    def make_thesis(candidate_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        try:
            tid=propose_thesis(conn,candidate_id)
            row=conn.execute("SELECT * FROM theses WHERE id=?",(tid,)).fetchone()
            return {"ok":True,"thesis":_json_fields(dict(row),["support_json","counter_json"])}
        except Exception as exc:
            raise HTTPException(400,str(exc)) from exc

    @router.get("/api/theses")
    def theses(status: str | None = None, conn: sqlite3.Connection = Depends(get_conn)):
        if status:
            rows=conn.execute(
                """
                SELECT t.*,c.title candidate_title
                FROM theses t JOIN candidates c ON c.id=t.candidate_id
                WHERE t.status=? ORDER BY t.created_at DESC
                """,
                (status.upper(),),
            ).fetchall()
        else:
            rows=conn.execute(
                """
                SELECT t.*,c.title candidate_title
                FROM theses t JOIN candidates c ON c.id=t.candidate_id
                ORDER BY t.created_at DESC
                """
            ).fetchall()
        return {"items":[_json_fields(dict(r),["support_json","counter_json"]) for r in rows]}

    @router.post("/api/theses/{thesis_id}/confirm")
    def confirm(thesis_id: str, body: ConfirmBody, conn: sqlite3.Connection = Depends(get_conn)):
        try:
            return {"ok":True,"ledger_id":confirm_thesis(conn,thesis_id,body.horizon)}
        except Exception as exc:
            raise HTTPException(400,str(exc)) from exc

    @router.post("/api/theses/{thesis_id}/hold")
    def hold(thesis_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        hold_thesis(conn,thesis_id)
        return {"ok":True}

    @router.post("/api/theses/{thesis_id}/draft")
    def draft(thesis_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        try:
            article_id,document_id=draft_article(conn,thesis_id)
            return {"ok":True,"article_id":article_id,"document_id":document_id}
        except Exception as exc:
            raise HTTPException(400,str(exc)) from exc

    @router.get("/api/articles")
    def articles(conn: sqlite3.Connection = Depends(get_conn)):
        rows=conn.execute(
            """
            SELECT a.*,c.title candidate_title,t.thesis,d.id document_id
            FROM articles a JOIN candidates c ON c.id=a.candidate_id
            JOIN theses t ON t.id=a.thesis_id LEFT JOIN documents d ON d.article_id=a.id
            ORDER BY a.updated_at DESC
            """
        ).fetchall()
        return {"items":[_json_fields(dict(r),["outline"]) for r in rows]}

    @router.get("/api/articles/{article_id}")
    def article(article_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        data=article_detail(conn,article_id)
        if not data:
            raise HTTPException(404,"article not found")
        return data

    @router.post("/api/articles/{article_id}/challenge")
    def challenge(article_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        try:
            return {"ok":True,"review_id":challenge_article(conn,article_id)}
        except Exception as exc:
            raise HTTPException(400,str(exc)) from exc

    @router.get("/api/trends")
    def trends(conn: sqlite3.Connection = Depends(get_conn)):
        rows=conn.execute(
            """
            SELECT t.*,
              COALESCE(SUM(CASE WHEN te.stance='SUPPORT' THEN 1 ELSE 0 END),0) support_count,
              COALESCE(SUM(CASE WHEN te.stance='COUNTER' THEN 1 ELSE 0 END),0) counter_count,
              COALESCE(SUM(CASE WHEN te.stance='UNCERTAIN' THEN 1 ELSE 0 END),0) uncertain_count
            FROM trends t LEFT JOIN trend_evidence te ON te.trend_id=t.id
            GROUP BY t.id
            ORDER BY CASE t.status WHEN 'ACTIVE' THEN 0 ELSE 1 END,t.updated_at DESC
            """
        ).fetchall()
        return {
            "items":[dict(r) for r in rows],
            "world_model":latest_world_model_update(conn),
        }

    @router.get("/api/trends/{trend_id}")
    def trend(trend_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        row=conn.execute("SELECT * FROM trends WHERE id=?",(trend_id,)).fetchone()
        if not row:
            raise HTTPException(404,"trend not found")
        evidence=conn.execute(
            "SELECT * FROM trend_evidence WHERE trend_id=? ORDER BY added_at DESC",
            (trend_id,),
        ).fetchall()
        revisions=conn.execute(
            "SELECT * FROM trend_revisions WHERE trend_id=? ORDER BY created_at DESC",
            (trend_id,),
        ).fetchall()
        return {
            "trend":dict(row),
            "evidence":[dict(x) for x in evidence],
            "revisions":[dict(x) for x in revisions],
        }

    @router.get("/api/ledger")
    def ledger(conn: sqlite3.Connection = Depends(get_conn)):
        rows=conn.execute(
            """
            SELECT jl.*,t.name trend_name,th.thesis
            FROM judgement_ledger jl
            LEFT JOIN trends t ON t.id=jl.trend_id
            LEFT JOIN theses th ON th.id=jl.thesis_id
            ORDER BY CASE WHEN jl.reviewed_at IS NULL THEN 0 ELSE 1 END,jl.created_at DESC
            """
        ).fetchall()
        return {"items":[dict(r) for r in rows]}

    @router.get("/api/intelligence")
    def intelligence(limit: int = 80, conn: sqlite3.Connection = Depends(get_conn)):
        rows=conn.execute(
            """
            SELECT i.*,s.name source_name
            FROM intelligence i JOIN sources s ON s.id=i.source_id
            ORDER BY COALESCE(i.published_at,i.collected_at) DESC
            LIMIT ?
            """,
            (max(1,min(limit,200)),),
        ).fetchall()
        return {"items":[dict(r) for r in rows]}

    return router
