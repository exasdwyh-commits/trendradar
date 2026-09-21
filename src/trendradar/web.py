from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from .db import connect, init_db
from .pipeline import today


def create_app(root: str | Path | None = None) -> FastAPI:
    root = Path(root or Path.cwd())
    db_path = root / "data" / "trendradar.db"
    conn = connect(db_path)
    init_db(conn, root / "schema.sql")

    app = FastAPI(title="TrendRadar Business", version="3.0.0")

    @app.get("/")
    def home():
        return FileResponse(root / "web" / "index.html")

    @app.get("/api/health")
    def health():
        last = conn.execute(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return {"ok": True, "last_run": dict(last) if last else None}

    @app.get("/api/today")
    def get_today(limit: int = 3):
        limit = max(1, min(limit, 5))
        return {"items": today(conn, limit)}

    @app.get("/api/trends")
    def trends():
        rows = conn.execute(
            """
            SELECT t.*,
              SUM(CASE WHEN te.stance='SUPPORT' THEN 1 ELSE 0 END) AS support_count,
              SUM(CASE WHEN te.stance='COUNTER' THEN 1 ELSE 0 END) AS counter_count
            FROM trends t
            LEFT JOIN trend_evidence te ON te.trend_id=t.id
            GROUP BY t.id
            ORDER BY t.updated_at DESC
            """
        ).fetchall()
        return {"items": [dict(r) for r in rows]}

    @app.get("/api/candidates/{candidate_id}")
    def candidate(candidate_id: str):
        row = conn.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
        if not row:
            raise HTTPException(404, "candidate not found")
        return dict(row)

    return app
