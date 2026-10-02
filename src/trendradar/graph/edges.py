"""Opportunity Graph as a relation table. Every derived relation is written here so the graph can be
exported to a graph database later without touching business tables."""

from __future__ import annotations

import json
import sqlite3

from ..core.ids import stable_id

RELATIONS = {
    "affects",
    "solved_by",
    "has_complaint",
    "belongs_to",
    "related_to",
    "derived_from",
    "competes_with",
    "supported_by",
    "alias_of",
}


def add_edge(
    conn: sqlite3.Connection,
    from_type: str,
    from_id: str,
    relation: str,
    to_type: str,
    to_id: str,
    *,
    weight: float = 1.0,
    meta: dict | None = None,
) -> str:
    if relation not in RELATIONS:
        raise ValueError(f"unknown relation {relation}")
    edge_id = stable_id("edge", from_type, from_id, relation, to_type, to_id)
    conn.execute(
        "INSERT OR REPLACE INTO edges(id,from_type,from_id,relation,to_type,to_id,weight,meta_json) VALUES(?,?,?,?,?,?,?,?)",
        (
            edge_id,
            from_type,
            from_id,
            relation,
            to_type,
            to_id,
            weight,
            json.dumps(meta or {}, ensure_ascii=False),
        ),
    )
    return edge_id


def neighbours(
    conn: sqlite3.Connection, node_type: str, node_id: str, *, relation: str | None = None, limit: int = 100
) -> list[dict]:
    where = "((from_type=? AND from_id=?) OR (to_type=? AND to_id=?))"
    params: list = [node_type, node_id, node_type, node_id]
    if relation:
        where += " AND relation=?"
        params.append(relation)
    rows = conn.execute(
        f"SELECT * FROM edges WHERE {where} ORDER BY weight DESC LIMIT ?", (*params, limit)
    ).fetchall()
    out = []
    for r in rows:
        outgoing = r["from_type"] == node_type and r["from_id"] == node_id
        out.append(
            {
                "relation": r["relation"],
                "direction": "out" if outgoing else "in",
                "type": r["to_type"] if outgoing else r["from_type"],
                "id": r["to_id"] if outgoing else r["from_id"],
                "weight": r["weight"],
                "meta": json.loads(r["meta_json"] or "{}"),
            }
        )
    return out
