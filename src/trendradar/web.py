from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .content import (
    create_blank_document, create_image_plan, create_platform_variant, edit_selection,
    export_variant, get_document, list_documents, list_publish_center,
    mark_variant_published, restore_version, save_document,
)
from .db import connect, init_db, schema_version
from .evaluation import calibration_summary, evaluation_summary, latest_blind_round, submit_blind_round
from .exporter import export_markdown, export_wechat_html
from .llm import slot_status
from .pipeline import today
from .trends import latest_world_model_update
from .writing import (
    article_detail, challenge_article, confirm_thesis, draft_article,
    hold_thesis, latest_research, propose_thesis, research_candidate,
)


class ConfirmBody(BaseModel):
    horizon: str = "12个月"


class DocumentCreateBody(BaseModel):
    title: str = "未命名文章"


class DocumentSaveBody(BaseModel):
    title: str
    content_json: dict
    content_html: str = ""
    plain_text: str = ""
    source: str = "MANUAL"
    note: str | None = None


class PlatformVariantBody(BaseModel):
    platform: str


class SelectionEditBody(BaseModel):
    selected_text: str
    instruction: str
    before_context: str = ""
    after_context: str = ""


class PublishedBody(BaseModel):
    external_url: str | None = None


class BlindSubmitBody(BaseModel):
    picks: list[str]


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
    bootstrap = connect(db_path)
    init_db(bootstrap, root / "schema.sql")
    bootstrap.close()

    def get_conn():
        connection = connect(db_path)
        try:
            yield connection
        finally:
            connection.close()

    output_dir = root / "output"
    frontend_dist = root / "frontend" / "dist"

    app = FastAPI(title="TrendRadar Business", version="3.1.0")
    if (frontend_dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

    @app.get("/")
    def home():
        index = frontend_dist / "index.html"
        if not index.exists():
            raise HTTPException(503, "frontend build missing: run cd frontend && npm install && npm run build")
        return FileResponse(index)

    @app.get("/api/health")
    def health(conn: sqlite3.Connection = Depends(get_conn)):
        last = conn.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()
        return {
            "ok": True,
            "schema_version": schema_version(conn),
            "last_run": dict(last) if last else None,
            "models": slot_status(),
        }

    @app.get("/api/dashboard")
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

    @app.get("/api/today")
    def get_today(limit: int = 3, conn: sqlite3.Connection = Depends(get_conn)):
        return {"items": today(conn, max(1, min(limit, 5)))}

    @app.get("/api/candidates")
    def candidates(limit: int = 30, conn: sqlite3.Connection = Depends(get_conn)):
        rows = conn.execute(
            "SELECT * FROM candidates ORDER BY updated_at DESC,content_score DESC LIMIT ?",
            (max(1,min(limit,100)),),
        ).fetchall()
        return {"items": [dict(r) for r in rows]}

    @app.get("/api/candidates/{candidate_id}")
    def candidate(candidate_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        row = conn.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
        if not row:
            raise HTTPException(404, "candidate not found")
        evidence = conn.execute(
            """
            SELECT i.* FROM cluster_items ci JOIN intelligence i ON i.id=ci.intelligence_id
            WHERE ci.cluster_id=? ORDER BY i.evidence_score DESC
            """,
            (row["cluster_id"],),
        ).fetchall()
        return {"candidate": dict(row), "evidence": [dict(x) for x in evidence], "research": latest_research(conn,candidate_id)}

    @app.post("/api/candidates/{candidate_id}/research")
    def start_research(candidate_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        try:
            return {"ok":True,"research_id":research_candidate(conn,candidate_id)}
        except Exception as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.post("/api/candidates/{candidate_id}/thesis")
    def make_thesis(candidate_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        try:
            tid=propose_thesis(conn,candidate_id)
            row=conn.execute("SELECT * FROM theses WHERE id=?",(tid,)).fetchone()
            return {"ok":True,"thesis":_json_fields(dict(row),["support_json","counter_json"])}
        except Exception as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.get("/api/theses")
    def theses(status: str | None = None, conn: sqlite3.Connection = Depends(get_conn)):
        if status:
            rows=conn.execute(
                """
                SELECT t.*,c.title candidate_title FROM theses t JOIN candidates c ON c.id=t.candidate_id
                WHERE t.status=? ORDER BY t.created_at DESC
                """,(status.upper(),)
            ).fetchall()
        else:
            rows=conn.execute(
                """
                SELECT t.*,c.title candidate_title FROM theses t JOIN candidates c ON c.id=t.candidate_id
                ORDER BY t.created_at DESC
                """
            ).fetchall()
        return {"items":[_json_fields(dict(r),["support_json","counter_json"]) for r in rows]}

    @app.post("/api/theses/{thesis_id}/confirm")
    def confirm(thesis_id: str, body: ConfirmBody, conn: sqlite3.Connection = Depends(get_conn)):
        try:
            return {"ok":True,"ledger_id":confirm_thesis(conn,thesis_id,body.horizon)}
        except Exception as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.post("/api/theses/{thesis_id}/hold")
    def hold(thesis_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        hold_thesis(conn,thesis_id); return {"ok":True}

    @app.post("/api/theses/{thesis_id}/draft")
    def draft(thesis_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        try:
            article_id,document_id=draft_article(conn,thesis_id)
            return {"ok":True,"article_id":article_id,"document_id":document_id}
        except Exception as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.get("/api/articles")
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

    @app.get("/api/articles/{article_id}")
    def article(article_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        data=article_detail(conn,article_id)
        if not data: raise HTTPException(404,"article not found")
        return data

    @app.post("/api/articles/{article_id}/challenge")
    def challenge(article_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        try:
            return {"ok":True,"review_id":challenge_article(conn,article_id)}
        except Exception as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.post("/api/articles/{article_id}/export/{format_name}")
    def export_article(article_id: str, format_name: str, conn: sqlite3.Connection = Depends(get_conn)):
        try:
            if format_name=="md": path=export_markdown(conn,article_id,output_dir)
            elif format_name=="wechat": path=export_wechat_html(conn,article_id,output_dir)
            else: raise ValueError("format must be md or wechat")
            return {"ok":True,"file":path.name,"url":f"/exports/{path.name}"}
        except Exception as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.get("/api/documents")
    def documents(conn: sqlite3.Connection = Depends(get_conn)):
        return {"items":list_documents(conn)}

    @app.post("/api/documents")
    def create_document(body: DocumentCreateBody, conn: sqlite3.Connection = Depends(get_conn)):
        return {"ok":True,"document_id":create_blank_document(conn,body.title)}

    @app.get("/api/documents/{document_id}")
    def document(document_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        data=get_document(conn,document_id)
        if not data: raise HTTPException(404,"document not found")
        return data

    @app.put("/api/documents/{document_id}")
    def update_document(document_id: str, body: DocumentSaveBody, conn: sqlite3.Connection = Depends(get_conn)):
        try:
            version=save_document(
                conn,document_id,body.title,body.content_json,body.content_html,
                body.plain_text,body.source,body.note,
            )
            return {"ok":True,"version":version}
        except Exception as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.post("/api/documents/{document_id}/restore/{version_number}")
    def restore_document(document_id: str, version_number: int, conn: sqlite3.Connection = Depends(get_conn)):
        try:
            return {"ok":True,"version":restore_version(conn,document_id,version_number)}
        except Exception as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.post("/api/documents/{document_id}/edit-selection")
    def document_edit_selection(document_id: str, body: SelectionEditBody, conn: sqlite3.Connection = Depends(get_conn)):
        try:
            return {
                "ok":True,
                **edit_selection(
                    conn,
                    document_id,
                    body.selected_text,
                    body.instruction,
                    body.before_context,
                    body.after_context,
                ),
            }
        except Exception as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.post("/api/documents/{document_id}/image-plan")
    def image_plan(document_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        try:
            return {"ok":True,"items":create_image_plan(conn,document_id)}
        except Exception as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.post("/api/documents/{document_id}/variant")
    def platform_variant(document_id: str, body: PlatformVariantBody, conn: sqlite3.Connection = Depends(get_conn)):
        try:
            return {"ok":True,"variant_id":create_platform_variant(conn,document_id,body.platform)}
        except Exception as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.get("/api/publish")
    def publish_center(conn: sqlite3.Connection = Depends(get_conn)):
        return {"items":list_publish_center(conn)}

    @app.post("/api/platform-variants/{variant_id}/published")
    def mark_published(variant_id: str, body: PublishedBody, conn: sqlite3.Connection = Depends(get_conn)):
        try:
            return {"ok":True,"publication_id":mark_variant_published(conn,variant_id,body.external_url)}
        except Exception as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.post("/api/platform-variants/{variant_id}/export")
    def export_platform_variant(variant_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        try:
            path=export_variant(conn,variant_id,output_dir/"platforms")
            return {"ok":True,"file":path.name,"url":f"/exports/platforms/{path.name}"}
        except Exception as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.get("/api/trends")
    def trends(conn: sqlite3.Connection = Depends(get_conn)):
        rows=conn.execute(
            """
            SELECT t.*,
              COALESCE(SUM(CASE WHEN te.stance='SUPPORT' THEN 1 ELSE 0 END),0) support_count,
              COALESCE(SUM(CASE WHEN te.stance='COUNTER' THEN 1 ELSE 0 END),0) counter_count,
              COALESCE(SUM(CASE WHEN te.stance='UNCERTAIN' THEN 1 ELSE 0 END),0) uncertain_count
            FROM trends t LEFT JOIN trend_evidence te ON te.trend_id=t.id
            GROUP BY t.id ORDER BY CASE t.status WHEN 'ACTIVE' THEN 0 ELSE 1 END,t.updated_at DESC
            """
        ).fetchall()
        return {"items":[dict(r) for r in rows],"world_model":latest_world_model_update(conn)}

    @app.get("/api/trends/{trend_id}")
    def trend(trend_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        row=conn.execute("SELECT * FROM trends WHERE id=?",(trend_id,)).fetchone()
        if not row: raise HTTPException(404,"trend not found")
        evidence=conn.execute("SELECT * FROM trend_evidence WHERE trend_id=? ORDER BY added_at DESC",(trend_id,)).fetchall()
        revisions=conn.execute("SELECT * FROM trend_revisions WHERE trend_id=? ORDER BY created_at DESC",(trend_id,)).fetchall()
        return {"trend":dict(row),"evidence":[dict(x) for x in evidence],"revisions":[dict(x) for x in revisions]}

    @app.get("/api/ledger")
    def ledger(conn: sqlite3.Connection = Depends(get_conn)):
        rows=conn.execute(
            """
            SELECT jl.*,t.name trend_name,th.thesis FROM judgement_ledger jl
            LEFT JOIN trends t ON t.id=jl.trend_id LEFT JOIN theses th ON th.id=jl.thesis_id
            ORDER BY CASE WHEN jl.reviewed_at IS NULL THEN 0 ELSE 1 END,jl.created_at DESC
            """
        ).fetchall()
        return {"items":[dict(r) for r in rows]}

    @app.get("/api/intelligence")
    def intelligence(limit: int = 80, conn: sqlite3.Connection = Depends(get_conn)):
        rows=conn.execute(
            """
            SELECT i.*,s.name source_name FROM intelligence i JOIN sources s ON s.id=i.source_id
            ORDER BY COALESCE(i.published_at,i.collected_at) DESC LIMIT ?
            """,(max(1,min(limit,200)),)
        ).fetchall()
        return {"items":[dict(r) for r in rows]}


    @app.get("/api/blind/latest")
    def blind_latest(conn: sqlite3.Connection = Depends(get_conn)):
        return {
            "round": latest_blind_round(conn),
            "summary": evaluation_summary(conn),
            "calibration": calibration_summary(conn),
        }

    @app.post("/api/blind/{round_id}/submit")
    def blind_submit(round_id: str, body: BlindSubmitBody, conn: sqlite3.Connection = Depends(get_conn)):
        try:
            return {
                "round": submit_blind_round(conn, round_id, body.picks),
                "summary": evaluation_summary(conn),
                "calibration": calibration_summary(conn),
            }
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/evaluation")
    def evaluation(conn: sqlite3.Connection = Depends(get_conn)):
        return {
            "summary":evaluation_summary(conn),
            "calibration":calibration_summary(conn),
        }

    @app.get("/api/ai-runs")
    def ai_runs(limit: int = 100, conn: sqlite3.Connection = Depends(get_conn)):
        rows = conn.execute(
            """
            SELECT * FROM ai_runs
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1,min(limit,300)),),
        ).fetchall()
        aggregate = conn.execute(
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
        return {"items":[dict(r) for r in rows],"aggregate":[dict(r) for r in aggregate]}

    @app.get("/api/source-yield")
    def source_yield(conn: sqlite3.Connection = Depends(get_conn)):
        rows = conn.execute(
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
            ORDER BY s.tier ASC, top3_count DESC, candidate_count DESC, s.name ASC
            """
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            total = item["intelligence_count"] or 0
            item["candidate_yield"] = round(item["candidate_count"]/total,4) if total else None
            item["write_yield"] = round(item["write_count"]/total,4) if total else None
            items.append(item)
        return {"items":items}

    @app.get("/api/sources")
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

    @app.get("/exports/{file_path:path}")
    def exports(file_path: str):
        path=(output_dir / file_path).resolve()
        if output_dir.resolve() not in path.parents and path!=output_dir.resolve():
            raise HTTPException(400,"invalid path")
        if not path.exists(): raise HTTPException(404,"export not found")
        return FileResponse(path)

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        index=frontend_dist/"index.html"
        if not index.exists():
            raise HTTPException(503, "frontend build missing: run cd frontend && npm install && npm run build")
        return FileResponse(index)

    return app
