"""Small, read-only overview for the daily creation workbench."""

import sqlite3

from .brief import get_brief
from .documents import STATUSES, list_documents


def get_overview(conn: sqlite3.Connection) -> dict:
    counts = dict.fromkeys(STATUSES, 0)
    counts.update(
        {
            r["status"]: r["count"]
            for r in conn.execute("SELECT status, COUNT(*) AS count FROM documents GROUP BY status")
        }
    )
    unfinished = conn.execute(
        "SELECT status FROM documents WHERE status IN ('idea','draft') ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()
    resume = None
    if unfinished:
        # Reuse the compact list projection, without loading bodies, versions or AI history.
        candidates = list_documents(conn, limit=1, status=unfinished["status"])
        resume = candidates[0] if candidates else None
    brief = get_brief(conn)
    topics = [
        item
        for section in ("story", "signal", "opportunity")
        for item in brief["sections"][section]
        if item["status"] == "new"
    ]
    return {
        "counts": counts,
        "resume": resume,
        "recent_documents": list_documents(conn, limit=6),
        "ready_documents": list_documents(conn, status="ready", limit=3),
        "material_count": conn.execute("SELECT COUNT(*) FROM materials WHERE archived=0").fetchone()[0],
        "recent_materials": brief["recent_materials"][:4],
        "topics": topics[:3],
        "topic_count": len(topics),
        "brief_day": brief["day"],
        "today": brief["today"],
    }
