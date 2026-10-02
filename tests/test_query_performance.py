"""Query-plan regressions: per-item lookups must not scan growing relation tables."""

import pytest


@pytest.mark.parametrize(
    "query, params",
    [
        ("SELECT COUNT(*) FROM document_materials WHERE material_id=?", ("material",)),
        ("SELECT COUNT(*) FROM publications WHERE document_id=?", ("document",)),
        (
            "SELECT * FROM publications WHERE document_id=? ORDER BY published_at DESC",
            ("document",),
        ),
    ],
)
def test_studio_relation_lookups_use_indexes(conn, query, params):
    plan = [row["detail"] for row in conn.execute("EXPLAIN QUERY PLAN " + query, params)]
    assert any("SEARCH" in detail for detail in plan), plan
    assert not any("USE TEMP B-TREE" in detail for detail in plan), plan


def test_index_migration_preserves_existing_studio_data(tmp_path):
    from trendradar.db.connection import connect
    from trendradar.db.migrate import available_migrations, migrate, schema_version
    from trendradar.studio.documents import create_document, get_document
    from trendradar.studio.materials import create_material, list_materials
    from trendradar.studio.publishing import publish_center, record_publication

    conn = connect(tmp_path / "studio-v6.db")
    try:
        for version, path in available_migrations():
            if version > 6:
                break
            conn.executescript(path.read_text(encoding="utf-8"))
            conn.execute(f"PRAGMA user_version={version}")
        material_id = create_material(conn, kind="note", title="已保存素材", content="正文")
        document_id = create_document(conn, title="已保存稿件", seed_material_id=material_id)
        record_publication(conn, document_id, platform="wechat", external_url="https://example.com/article")
        before = (get_document(conn, document_id), list_materials(conn), publish_center(conn))

        assert migrate(conn) == [7, 8]
        assert schema_version(conn) == 8
        assert (get_document(conn, document_id), list_materials(conn), publish_center(conn)) == before
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert migrate(conn) == []
    finally:
        conn.close()
