from __future__ import annotations

import json
import sqlite3
import uuid


def freeze_publication_snapshot(
    conn: sqlite3.Connection,
    *,
    document_id: str,
    variant_id: str | None = None,
    publication_id: str | None = None,
    reason: str = "PUBLISHED",
) -> str:
    document = conn.execute(
        "SELECT * FROM documents WHERE id=?",
        (document_id,),
    ).fetchone()
    if not document:
        raise KeyError("document not found")

    version = conn.execute(
        """
        SELECT * FROM document_versions
        WHERE document_id=?
        ORDER BY version_number DESC
        LIMIT 1
        """,
        (document_id,),
    ).fetchone()
    thesis = None
    candidate = None
    research = None
    evidence = []
    if document["thesis_id"]:
        row = conn.execute("SELECT * FROM theses WHERE id=?", (document["thesis_id"],)).fetchone()
        thesis = dict(row) if row else None
    if document["candidate_id"]:
        row = conn.execute("SELECT * FROM candidates WHERE id=?", (document["candidate_id"],)).fetchone()
        if row:
            candidate = dict(row)
            evidence = [
                dict(x) for x in conn.execute(
                    """
                    SELECT i.* FROM cluster_items ci
                    JOIN intelligence i ON i.id=ci.intelligence_id
                    WHERE ci.cluster_id=?
                    ORDER BY i.evidence_score DESC
                    """,
                    (row["cluster_id"],),
                ).fetchall()
            ]
        r = conn.execute(
            """
            SELECT * FROM research
            WHERE candidate_id=?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (document["candidate_id"],),
        ).fetchone()
        research = dict(r) if r else None

    variant = None
    if variant_id:
        row = conn.execute("SELECT * FROM platform_variants WHERE id=?", (variant_id,)).fetchone()
        variant = dict(row) if row else None

    publication = None
    if publication_id:
        row = conn.execute("SELECT * FROM publications WHERE id=?", (publication_id,)).fetchone()
        publication = dict(row) if row else None

    payload = {
        "document":dict(document),
        "version":dict(version) if version else None,
        "candidate":candidate,
        "thesis":thesis,
        "research":research,
        "evidence":evidence,
        "variant":variant,
        "publication":publication,
    }
    snapshot_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO content_snapshots(
          id,document_id,variant_id,publication_id,candidate_id,thesis_id,reason,snapshot_json
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            snapshot_id,document_id,variant_id,publication_id,
            document["candidate_id"],document["thesis_id"],reason,
            json.dumps(payload,ensure_ascii=False),
        ),
    )
    conn.commit()
    return snapshot_id
