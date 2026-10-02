from fastapi import FastAPI
from fastapi.testclient import TestClient

from trendradar.api.studio import build_router
from trendradar.studio.documents import create_document, update_document
from trendradar.studio.materials import create_material


def overview(conn):
    app = FastAPI()
    app.include_router(build_router(lambda: conn))
    with TestClient(app) as client:
        response = client.get("/api/studio/overview")
    assert response.status_code == 200, response.text
    return response.json()


def test_empty_workbench_is_read_only(conn):
    changes = conn.total_changes
    data = overview(conn)
    assert data["counts"] == {"idea": 0, "draft": 0, "ready": 0, "published": 0, "archived": 0}
    assert data["resume"] is None
    assert data["recent_documents"] == []
    assert data["ready_documents"] == []
    assert data["topics"] == []
    assert data["material_count"] == 0
    assert conn.total_changes == changes


def test_workbench_resumes_unfinished_work_and_counts_all_documents(conn):
    draft = create_document(conn, title="继续写这篇", content_md="正文", status="draft")
    ready = create_document(conn, title="待发布", status="ready")
    create_document(conn, title="已发布", status="published")
    archived = create_document(conn, title="已归档", status="archived")
    conn.execute("UPDATE documents SET updated_at='2099-01-01T00:00:00Z' WHERE id=?", (archived,))
    conn.execute("UPDATE documents SET updated_at='2090-01-01T00:00:00Z' WHERE id=?", (draft,))
    conn.executemany(
        "INSERT INTO documents(id,title) VALUES(?,?)", [(f"idea-{i}", "旧选题") for i in range(210)]
    )
    create_material(conn, kind="note", title="可用笔记")
    hidden = create_material(conn, kind="note", title="归档笔记")
    conn.execute("UPDATE materials SET archived=1 WHERE id=?", (hidden,))
    conn.commit()
    data = overview(conn)
    assert data["resume"]["id"] == draft
    assert data["counts"]["idea"] == 210
    assert data["counts"]["archived"] == 1
    assert len(data["recent_documents"]) == 6
    assert archived not in {d["id"] for d in data["recent_documents"]}
    assert [d["id"] for d in data["ready_documents"]] == [ready]
    assert data["material_count"] == 1
    assert "content_md" not in data["resume"]
    update_document(conn, draft, {"status": "ready"})
    assert overview(conn)["resume"]["id"] != draft
