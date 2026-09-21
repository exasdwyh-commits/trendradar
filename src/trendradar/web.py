from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .db import connect, init_db
from .exporter import export_markdown, export_wechat_html
from .llm import slot_status
from .pipeline import today
from .trends import latest_world_model_update
from .writing import (
    article_detail, challenge_article, confirm_thesis, draft_article,
    hold_thesis, latest_research, mark_article_ready, propose_thesis,
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


def create_app(root: str | Path | None = None) -> FastAPI:
    root = Path(root or Path.cwd())
    db_path = root / "data" / "trendradar.db"
    conn = connect(db_path)
    init_db(conn, root / "schema.sql")
    output_dir = root / "output"

    app = FastAPI(title="TrendRadar Business", version="3.0.0")

    @app.get("/")
    def home():
        return FileResponse(root / "web" / "index.html")

    @app.get("/api/health")
    def health():
        last = conn.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()
        return {"ok": True, "last_run": dict(last) if last else None, "models": slot_status()}

    @app.get("/api/dashboard")
    def dashboard():
        pending = conn.execute(
            """
            SELECT t.*,c.title candidate_title
            FROM theses t JOIN candidates c ON c.id=t.candidate_id
            WHERE t.status='PENDING'
            ORDER BY t.created_at DESC LIMIT 5
            """
        ).fetchall()
        active_research = conn.execute(
            """
            SELECT r.*,c.title candidate_title
            FROM research r JOIN candidates c ON c.id=r.candidate_id
            ORDER BY r.created_at DESC LIMIT 5
            """
        ).fetchall()
        return {
            "today": today(conn, 3),
            "pending_decisions": [dict(x) for x in pending],
            "recent_research": [dict(x) for x in active_research],
            "world_model": latest_world_model_update(conn),
        }

    @app.get("/api/today")
    def get_today(limit: int = 3):
        return {"items": today(conn, max(1, min(limit, 5)))}

    @app.get("/api/candidates")
    def candidates(limit: int = 30):
        rows = conn.execute(
            """
            SELECT * FROM candidates
            ORDER BY updated_at DESC,content_score DESC
            LIMIT ?
            """,
            (max(1,min(limit,100)),),
        ).fetchall()
        return {"items": [dict(r) for r in rows]}

    @app.get("/api/candidates/{candidate_id}")
    def candidate(candidate_id: str):
        row = conn.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
        if not row:
            raise HTTPException(404, "candidate not found")
        evidence = conn.execute(
            """
            SELECT i.* FROM cluster_items ci
            JOIN intelligence i ON i.id=ci.intelligence_id
            WHERE ci.cluster_id=?
            ORDER BY i.evidence_score DESC
            """,
            (row["cluster_id"],),
        ).fetchall()
        return {"candidate": dict(row), "evidence": [dict(x) for x in evidence], "research": latest_research(conn,candidate_id)}

    @app.post("/api/candidates/{candidate_id}/research")
    def start_research(candidate_id: str):
        try:
            rid = research_candidate(conn, candidate_id)
            return {"ok": True, "research_id": rid}
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/candidates/{candidate_id}/thesis")
    def make_thesis(candidate_id: str):
        try:
            tid = propose_thesis(conn, candidate_id)
            row = conn.execute("SELECT * FROM theses WHERE id=?", (tid,)).fetchone()
            data = _json_fields(dict(row), ["support_json","counter_json"])
            return {"ok": True, "thesis": data}
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/theses")
    def theses(status: str | None = None):
        if status:
            rows = conn.execute(
                """
                SELECT t.*,c.title candidate_title FROM theses t
                JOIN candidates c ON c.id=t.candidate_id
                WHERE t.status=? ORDER BY t.created_at DESC
                """,
                (status.upper(),),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT t.*,c.title candidate_title FROM theses t
                JOIN candidates c ON c.id=t.candidate_id
                ORDER BY t.created_at DESC
                """
            ).fetchall()
        return {"items": [_json_fields(dict(r),["support_json","counter_json"]) for r in rows]}

    @app.post("/api/theses/{thesis_id}/confirm")
    def confirm(thesis_id: str, body: ConfirmBody):
        try:
            ledger_id = confirm_thesis(conn, thesis_id, body.horizon)
            return {"ok": True, "ledger_id": ledger_id}
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/theses/{thesis_id}/hold")
    def hold(thesis_id: str):
        hold_thesis(conn, thesis_id)
        return {"ok": True}

    @app.post("/api/theses/{thesis_id}/draft")
    def draft(thesis_id: str):
        try:
            aid = draft_article(conn, thesis_id)
            return {"ok": True, "article_id": aid}
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/articles")
    def articles():
        rows = conn.execute(
            """
            SELECT a.*,c.title candidate_title,t.thesis
            FROM articles a
            JOIN candidates c ON c.id=a.candidate_id
            JOIN theses t ON t.id=a.thesis_id
            ORDER BY a.updated_at DESC
            """
        ).fetchall()
        return {"items": [_json_fields(dict(r),["outline"]) for r in rows]}

    @app.get("/api/articles/{article_id}")
    def article(article_id: str):
        data = article_detail(conn, article_id)
        if not data:
            raise HTTPException(404, "article not found")
        return data

    @app.post("/api/articles/{article_id}/challenge")
    def challenge(article_id: str):
        try:
            review_id = challenge_article(conn, article_id)
            return {"ok": True, "review_id": review_id}
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/articles/{article_id}/ready")
    def ready(article_id: str):
        mark_article_ready(conn, article_id)
        return {"ok": True}

    @app.post("/api/articles/{article_id}/export/{format_name}")
    def export(article_id: str, format_name: str):
        try:
            if format_name == "md":
                path = export_markdown(conn, article_id, output_dir)
            elif format_name == "wechat":
                path = export_wechat_html(conn, article_id, output_dir)
            else:
                raise ValueError("format must be md or wechat")
            return {"ok": True, "file": path.name, "url": f"/exports/{path.name}"}
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/exports/{filename}")
    def exports(filename: str):
        safe = Path(filename).name
        path = output_dir / safe
        if not path.exists():
            raise HTTPException(404, "export not found")
        return FileResponse(path)

    @app.get("/api/trends")
    def trends():
        rows = conn.execute(
            """
            SELECT t.*,
              COALESCE(SUM(CASE WHEN te.stance='SUPPORT' THEN 1 ELSE 0 END),0) support_count,
              COALESCE(SUM(CASE WHEN te.stance='COUNTER' THEN 1 ELSE 0 END),0) counter_count,
              COALESCE(SUM(CASE WHEN te.stance='UNCERTAIN' THEN 1 ELSE 0 END),0) uncertain_count
            FROM trends t
            LEFT JOIN trend_evidence te ON te.trend_id=t.id
            GROUP BY t.id
            ORDER BY CASE t.status WHEN 'ACTIVE' THEN 0 ELSE 1 END,t.updated_at DESC
            """
        ).fetchall()
        return {"items": [dict(r) for r in rows], "world_model": latest_world_model_update(conn)}

    @app.get("/api/trends/{trend_id}")
    def trend(trend_id: str):
        row = conn.execute("SELECT * FROM trends WHERE id=?", (trend_id,)).fetchone()
        if not row:
            raise HTTPException(404, "trend not found")
        evidence = conn.execute(
            "SELECT * FROM trend_evidence WHERE trend_id=? ORDER BY added_at DESC",
            (trend_id,),
        ).fetchall()
        revisions = conn.execute(
            "SELECT * FROM trend_revisions WHERE trend_id=? ORDER BY created_at DESC",
            (trend_id,),
        ).fetchall()
        return {"trend": dict(row), "evidence": [dict(x) for x in evidence], "revisions": [dict(x) for x in revisions]}

    @app.get("/api/ledger")
    def ledger():
        rows = conn.execute(
            """
            SELECT jl.*,t.name trend_name,th.thesis
            FROM judgement_ledger jl
            LEFT JOIN trends t ON t.id=jl.trend_id
            LEFT JOIN theses th ON th.id=jl.thesis_id
            ORDER BY CASE WHEN jl.reviewed_at IS NULL THEN 0 ELSE 1 END,jl.created_at DESC
            """
        ).fetchall()
        return {"items": [dict(r) for r in rows]}

    @app.get("/api/intelligence")
    def intelligence(limit: int = 80):
        rows = conn.execute(
            """
            SELECT i.*,s.name source_name FROM intelligence i
            JOIN sources s ON s.id=i.source_id
            ORDER BY COALESCE(i.published_at,i.collected_at) DESC LIMIT ?
            """,
            (max(1,min(limit,200)),),
        ).fetchall()
        return {"items": [dict(r) for r in rows]}

    @app.get("/api/sources")
    def sources():
        rows = conn.execute(
            """
            SELECT s.*,h.last_attempt_at,h.last_success_at,h.last_error,
              h.consecutive_failures,h.last_item_count,h.latency_ms
            FROM sources s LEFT JOIN source_health h ON h.source_id=s.id
            ORDER BY s.role,s.lane,s.name
            """
        ).fetchall()
        return {"items": [dict(r) for r in rows]}

    return app
