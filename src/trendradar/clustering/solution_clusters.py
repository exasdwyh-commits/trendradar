"""Supply side: embed products and group them into solution clusters."""

from __future__ import annotations

import json
import sqlite3

import numpy as np

from ..core.ids import stable_id
from ..core.timeutil import days_ago, iso, utcnow
from ..providers.embeddings import EmbeddingProvider, from_blob, to_blob
from .index import normalize, store_vectors


def product_text(row: sqlite3.Row | dict) -> str:
    cats = (
        " ".join(json.loads(row["categories_json"] or "[]"))
        if isinstance(row["categories_json"], str)
        else ""
    )
    return f"{row['name']}. {row['tagline'] or ''}. {(row['description'] or '')[:1200]} {cats}"


def embed_pending_products(conn: sqlite3.Connection, embedder: EmbeddingProvider, batch: int = 200) -> int:
    rows = conn.execute(
        """SELECT p.id, p.name, p.tagline, p.description, p.categories_json FROM products p
           LEFT JOIN product_embeddings e ON e.product_id=p.id AND e.model=? WHERE e.product_id IS NULL AND p.alias_of IS NULL""",
        (embedder.name,),
    ).fetchall()
    total = 0
    for start in range(0, len(rows), batch):
        chunk = rows[start : start + batch]
        matrix = embedder.embed([product_text(r) for r in chunk], conn=conn, task="embed_products")
        store_vectors(conn, "product_embeddings", embedder.name, [r["id"] for r in chunk], matrix)
        conn.commit()
        total += len(chunk)
    return total


def cluster_pending_products(
    conn: sqlite3.Connection, embedder: EmbeddingProvider, *, threshold: float
) -> dict:
    model = embedder.name
    rows = conn.execute(
        """SELECT p.id, p.name, p.votes, p.origin, e.dim, e.vector FROM products p
           JOIN product_embeddings e ON e.product_id=p.id AND e.model=?
           LEFT JOIN product_cluster_items i ON i.product_id=p.id WHERE i.product_id IS NULL AND p.alias_of IS NULL
           ORDER BY p.votes DESC""",
        (model,),
    ).fetchall()
    clusters = []
    for r in conn.execute(
        "SELECT id, centroid, product_count FROM product_clusters WHERE centroid_model=?", (model,)
    ):
        if r["centroid"] is not None:
            clusters.append(
                {
                    "id": r["id"],
                    "centroid": normalize(np.frombuffer(r["centroid"], dtype=np.float32).copy()),
                    "n": max(1, int(r["product_count"] or 0)),
                }
            )
    created = assigned = 0
    touched: set[str] = set()
    for r in rows:
        vec = normalize(from_blob(r["vector"], int(r["dim"])))
        best, best_sim = None, -1.0
        for c in clusters:
            sim = float(vec @ c["centroid"])
            if sim > best_sim:
                best, best_sim = c, sim
        if best is not None and best_sim >= threshold:
            cid = best["id"]
            best["centroid"] = normalize(best["centroid"] * best["n"] + vec)
            best["n"] += 1
            assigned += 1
        else:
            cid = stable_id("product_cluster", model, r["id"])
            conn.execute(
                "INSERT OR IGNORE INTO product_clusters(id,label,centroid_model,data_mode) VALUES(?,?,?,?)",
                (cid, r["name"][:200], model, r["origin"]),
            )
            clusters.append({"id": cid, "centroid": vec.copy(), "n": 1})
            created += 1
        conn.execute(
            "INSERT OR IGNORE INTO product_cluster_items(cluster_id,product_id,similarity) VALUES(?,?,?)",
            (cid, r["id"], round(max(best_sim, 0.0) if best else 1.0, 4)),
        )
        touched.add(cid)
    for c in clusters:
        if c["id"] in touched:
            conn.execute(
                "UPDATE product_clusters SET centroid=?, updated_at=? WHERE id=?",
                (to_blob(c["centroid"]), iso(utcnow()), c["id"]),
            )
    for cid in touched:
        refresh_product_cluster_stats(conn, cid)
    conn.commit()
    return {"created": created, "assigned_existing": assigned, "clusters_touched": len(touched)}


def refresh_product_cluster_stats(conn: sqlite3.Connection, cluster_id: str) -> None:
    cutoff = iso(days_ago(90))
    row = conn.execute(
        """SELECT COUNT(*) n, SUM(CASE WHEN p.launched_at>=? THEN 1 ELSE 0 END) new_90d, AVG(p.rating) avg_rating, SUM(p.votes) votes,
                  SUM(CASE WHEN p.origin='mock' THEN 1 ELSE 0 END) mocks, MAX(p.votes) top_votes
           FROM product_cluster_items i JOIN products p ON p.id=i.product_id WHERE i.cluster_id=?""",
        (cutoff, cluster_id),
    ).fetchone()
    n = int(row["n"] or 0)
    mocks = int(row["mocks"] or 0)
    top = int(row["top_votes"] or 0)
    maturity = (
        "nascent"
        if n <= 1 and top < 200
        else "emerging"
        if n <= 3 or top < 500
        else "established"
        if n <= 8
        else "crowded"
    )
    label_row = conn.execute(
        "SELECT p.name FROM product_cluster_items i JOIN products p ON p.id=i.product_id WHERE i.cluster_id=? ORDER BY p.votes DESC LIMIT 1",
        (cluster_id,),
    ).fetchone()
    conn.execute(
        "UPDATE product_clusters SET product_count=?, new_90d=?, avg_rating=?, total_votes=?, maturity=?, data_mode=?, label=COALESCE(label,?), updated_at=? WHERE id=?",
        (
            n,
            int(row["new_90d"] or 0),
            row["avg_rating"],
            int(row["votes"] or 0),
            maturity,
            "mock" if n and mocks == n else "live" if mocks == 0 else "mixed",
            label_row["name"] if label_row else None,
            iso(utcnow()),
            cluster_id,
        ),
    )
