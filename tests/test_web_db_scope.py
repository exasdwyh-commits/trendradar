from pathlib import Path

from fastapi.testclient import TestClient

from trendradar.db import CURRENT_SCHEMA_VERSION
from trendradar.web import create_app

ROOT=Path(__file__).resolve().parents[1]


def app_root(tmp_path: Path) -> Path:
    (tmp_path/"schema.sql").write_text(
        (ROOT/"schema.sql").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return tmp_path


def test_web_api_uses_initialized_request_scoped_database(tmp_path):
    app=create_app(app_root(tmp_path))
    with TestClient(app) as client:
        health=client.get("/api/health")
        assert health.status_code==200
        assert health.json()["schema_version"]==CURRENT_SCHEMA_VERSION

        first=client.post("/api/documents",json={"title":"A"})
        second=client.post("/api/documents",json={"title":"B"})
        assert first.status_code==200
        assert second.status_code==200

        docs=client.get("/api/documents")
        assert docs.status_code==200
        titles={item["title"] for item in docs.json()["items"]}
        assert {"A","B"} <= titles
