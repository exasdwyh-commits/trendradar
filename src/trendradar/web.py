from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import build_content_router, build_editorial_router, build_ops_router
from .db import connect, init_db


def create_app(root: str | Path | None = None) -> FastAPI:
    root=Path(root or Path.cwd())
    db_path=root/"data"/"trendradar.db"

    # Bootstrap/migrate once, then every API request receives its own connection.
    # This avoids sharing transaction state across concurrent FastAPI worker threads.
    bootstrap=connect(db_path)
    init_db(bootstrap,root/"schema.sql")
    bootstrap.close()

    def get_conn():
        connection=connect(db_path)
        try:
            yield connection
        finally:
            connection.close()

    output_dir=root/"output"
    frontend_dist=root/"frontend"/"dist"

    app=FastAPI(title="TrendRadar Business",version="3.1.0")

    if (frontend_dist/"assets").exists():
        app.mount("/assets",StaticFiles(directory=frontend_dist/"assets"),name="assets")

    app.include_router(build_editorial_router(get_conn))
    app.include_router(build_content_router(get_conn,output_dir))
    app.include_router(build_ops_router(get_conn))

    @app.get("/")
    def home():
        index=frontend_dist/"index.html"
        if not index.exists():
            raise HTTPException(
                503,
                "frontend build missing: run cd frontend && npm install && npm run build",
            )
        return FileResponse(index)

    @app.get("/exports/{file_path:path}")
    def exports(file_path: str):
        path=(output_dir/file_path).resolve()
        if output_dir.resolve() not in path.parents and path!=output_dir.resolve():
            raise HTTPException(400,"invalid path")
        if not path.exists():
            raise HTTPException(404,"export not found")
        return FileResponse(path)

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        index=frontend_dist/"index.html"
        if not index.exists():
            raise HTTPException(
                503,
                "frontend build missing: run cd frontend && npm install && npm run build",
            )
        return FileResponse(index)

    return app
