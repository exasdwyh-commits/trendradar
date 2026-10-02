"""Pain clustering: classified pain signals → persona-blocked, centroid-based clusters.

Blocking by persona is deliberate: "developers can't manage agent sessions" and "freelancers can't
manage client sessions" are different opportunities even if the wording overlaps, and it makes the
degraded (local hash embedding) path behave. Within a block, incremental leader clustering assigns a
signal to the most similar existing centroid if cosine ≥ τ, else starts a new cluster.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

import numpy as np

from ..core.ids import stable_id
from ..core.logging import get_logger
from ..core.timeutil import iso, utcnow
from ..providers.embeddings import EmbeddingProvider, from_blob, to_blob
from ..providers.llm import resolve_llm
from .index import VectorIndex, normalize, store_vectors

log = get_logger("clustering")

SEMANTIC_DUP_THRESHOLD = 0.97


@dataclass
class ClusterStats:
    embedded: int = 0
    assigned_existing: int = 0
    created: int = 0
    semantic_duplicates: int = 0
    labeled: int = 0
    clusters_touched: set[str] = field(default_factory=set)

    def as_dict(self) -> dict:
        return {
            "embedded": self.embedded,
            "assigned_existing": self.assigned_existing,
            "created": self.created,
            "semantic_duplicates": self.semantic_duplicates,
            "labeled": self.labeled,
            "clusters_touched": len(self.clusters_touched),
        }


def signal_text(row: sqlite3.Row | dict) -> str:
    return f"{row['title']}. {row['content'][:1500]}"


# ───────────────────────── embedding ─────────────────────────


def embed_pending_signals(
    conn: sqlite3.Connection,
    embedder: EmbeddingProvider,
    *,
    min_relevance: float,
    batch: int = 200,
    session_id: str | None = None,
) -> int:
    """Embed classified pain signals that have no vector for the active model.

    For the local (degraded) provider every classified signal lacking a vector is embedded, so
    switching to a real embedding model later simply re-embeds everything under the new model name.
    """
    rows = conn.execute(
        """
        SELECT s.id, s.title, s.content FROM signals s
        JOIN signal_classifications c ON c.signal_id=s.id
        LEFT JOIN signal_embeddings e ON e.signal_id=s.id AND e.model=?
        WHERE e.signal_id IS NULL AND c.is_pain=1 AND c.relevance>=? AND s.status IN ('classified','embedded','clustered') AND s.dedup_of IS NULL
        """,
        (embedder.name, min_relevance),
    ).fetchall()
    total = 0
    for start in range(0, len(rows), batch):
        chunk = rows[start : start + batch]
        matrix = embedder.embed([signal_text(r) for r in chunk], conn=conn, task="embed_signals")
        store_vectors(conn, "signal_embeddings", embedder.name, [r["id"] for r in chunk], matrix)
        conn.executemany(
            "UPDATE signals SET status='embedded' WHERE id=? AND status='classified'",
            [(r["id"],) for r in chunk],
        )
        conn.commit()
        total += len(chunk)
    return total


# ───────────────────────── clustering ─────────────────────────


def _block_key(origin: str, persona: str | None, category: str | None) -> str:
    """Clustering block: live and mock data never share a cluster; within an origin we block by persona."""
    return f"{origin}:{persona or category or 'other'}"


def _load_block_clusters(
    conn: sqlite3.Connection, model: str, block: str, session_id: str | None
) -> list[dict]:
    origin, persona_block = block.split(":", 1)
    rows = conn.execute(
        "SELECT id, centroid, persona, category, signal_count FROM pain_clusters WHERE centroid_model=? AND data_mode=? AND COALESCE(persona,category,'other')=? AND session_id IS ? ",
        (model, origin, persona_block, session_id),
    ).fetchall()
    out = []
    for r in rows:
        if r["centroid"] is None:
            continue
        vec = normalize(np.frombuffer(r["centroid"], dtype=np.float32).copy())
        out.append({"id": r["id"], "centroid": vec, "n": max(1, int(r["signal_count"] or 0))})
    return out


def cluster_pending_signals(
    conn: sqlite3.Connection,
    embedder: EmbeddingProvider,
    *,
    threshold: float,
    session_id: str | None = None,
    signal_ids: list[str] | None = None,
) -> ClusterStats:
    """Assign embedded pain signals to clusters.

    Global scope (session_id=None): every embedded signal not yet in a global cluster.
    Session scope (Explore): only `signal_ids`, into clusters tagged with that session — a signal may
    therefore live in one global cluster and any number of session clusters.
    """
    stats = ClusterStats()
    model = embedder.name
    scope_clause = "pc.session_id IS NULL" if session_id is None else "pc.session_id=?"
    scope_params: list = [] if session_id is None else [session_id]
    id_clause = ""
    id_params: list = []
    if signal_ids is not None:
        if not signal_ids:
            return stats
        id_clause = f" AND s.id IN ({','.join('?' * len(signal_ids))})"
        id_params = list(signal_ids)
    rows = conn.execute(
        f"""
        SELECT s.id, s.title, s.content, s.author_id, s.source_id, s.origin, s.created_at, s.engagement_json,
               c.persona, c.category, e.dim, e.vector
        FROM signals s
        JOIN signal_classifications c ON c.signal_id=s.id
        JOIN signal_embeddings e ON e.signal_id=s.id AND e.model=?
        WHERE s.dedup_of IS NULL AND s.status IN ('embedded','clustered')
          AND NOT EXISTS (
            SELECT 1 FROM pain_cluster_items pci JOIN pain_clusters pc ON pc.id=pci.cluster_id
            WHERE pci.signal_id=s.id AND {scope_clause}
          ){id_clause}
        """,
        (model, *scope_params, *id_params),
    ).fetchall()

    def engagement(r: sqlite3.Row) -> int:
        try:
            e = json.loads(r["engagement_json"] or "{}")
            return int(e.get("votes", 0)) + int(e.get("comments", 0))
        except (TypeError, ValueError):
            return 0

    rows = sorted(rows, key=engagement, reverse=True)  # strongest statements seed clusters
    blocks: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        blocks.setdefault(_block_key(r["origin"], r["persona"], r["category"]), []).append(r)

    for block, members in blocks.items():
        clusters = _load_block_clusters(conn, model, block, session_id)  # centroid = unit vector, n = size
        for r in members:
            vec = normalize(from_blob(r["vector"], int(r["dim"])))
            best, best_sim = None, -1.0
            for c in clusters:
                sim = float(vec @ c["centroid"])
                if sim > best_sim:
                    best, best_sim = c, sim
            if best is not None and best_sim >= threshold:
                if best_sim >= SEMANTIC_DUP_THRESHOLD and _near_identical_in_cluster(
                    conn, best["id"], vec, model
                ):
                    original = conn.execute(
                        "SELECT signal_id FROM pain_cluster_items WHERE cluster_id=? LIMIT 1", (best["id"],)
                    ).fetchone()
                    conn.execute(
                        "UPDATE signals SET status='duplicate', dedup_of=? WHERE id=?",
                        (original["signal_id"] if original else None, r["id"]),
                    )
                    stats.semantic_duplicates += 1
                    continue
                cluster_id = best["id"]
                best["centroid"] = normalize(best["centroid"] * best["n"] + vec)
                best["n"] += 1
                stats.assigned_existing += 1
                sim_value = best_sim
            else:
                cluster_id = stable_id("pain_cluster", model, block, session_id or "global", r["id"])
                conn.execute(
                    "INSERT OR IGNORE INTO pain_clusters(id,label,persona,category,centroid_model,label_source,data_mode,session_id) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        cluster_id,
                        r["title"][:200] or "Untitled",
                        r["persona"],
                        r["category"],
                        model,
                        "rule",
                        r["origin"],
                        session_id,
                    ),
                )
                clusters.append({"id": cluster_id, "centroid": vec.copy(), "n": 1})
                stats.created += 1
                sim_value = 1.0
            conn.execute(
                "INSERT OR IGNORE INTO pain_cluster_items(cluster_id,signal_id,similarity) VALUES(?,?,?)",
                (cluster_id, r["id"], round(sim_value, 4)),
            )
            conn.execute("UPDATE signals SET status='clustered' WHERE id=?", (r["id"],))
            stats.clusters_touched.add(cluster_id)
        for c in clusters:
            if c["id"] in stats.clusters_touched:
                conn.execute(
                    "UPDATE pain_clusters SET centroid=?, updated_at=? WHERE id=?",
                    (to_blob(c["centroid"]), iso(utcnow()), c["id"]),
                )
    conn.commit()
    for cluster_id in stats.clusters_touched:
        refresh_cluster_stats(conn, cluster_id)
    conn.commit()
    return stats


def _near_identical_in_cluster(
    conn: sqlite3.Connection, cluster_id: str, vec: np.ndarray, model: str
) -> bool:
    ids = [
        r["signal_id"]
        for r in conn.execute("SELECT signal_id FROM pain_cluster_items WHERE cluster_id=?", (cluster_id,))
    ]
    index = VectorIndex.load(conn, "signal_embeddings", model, ids=ids)
    hits = index.search(vec, k=1)
    return bool(hits) and hits[0][1] >= SEMANTIC_DUP_THRESHOLD


def refresh_cluster_stats(conn: sqlite3.Connection, cluster_id: str) -> None:
    row = conn.execute(
        """
        SELECT COUNT(*) n, COUNT(DISTINCT COALESCE(s.author_id, s.author, s.id)) users, COUNT(DISTINCT s.source_id) sources,
               MIN(COALESCE(s.created_at, s.fetched_at)) first_seen, MAX(COALESCE(s.created_at, s.fetched_at)) last_seen,
               SUM(CASE WHEN s.origin='mock' THEN 1 ELSE 0 END) mocks
        FROM pain_cluster_items pci JOIN signals s ON s.id=pci.signal_id WHERE pci.cluster_id=?
        """,
        (cluster_id,),
    ).fetchone()
    n = int(row["n"] or 0)
    mocks = int(row["mocks"] or 0)
    data_mode = "mock" if n and mocks == n else "live" if mocks == 0 else "mixed"
    conn.execute(
        "UPDATE pain_clusters SET signal_count=?, unique_users=?, source_count=?, first_seen=?, last_seen=?, data_mode=?, updated_at=? WHERE id=?",
        (
            n,
            int(row["users"] or 0),
            int(row["sources"] or 0),
            row["first_seen"],
            row["last_seen"],
            data_mode,
            iso(utcnow()),
            cluster_id,
        ),
    )


# ───────────────────────── labelling ─────────────────────────

LABEL_SYSTEM = """You name clusters of user complaints for a software opportunity radar.
For each cluster write: label (≤ 12 words, a problem statement like "Managing multiple AI coding sessions is chaotic"), summary (2 sentences: who, what problem, current workaround), persona (developer, designer, marketer, freelancer, startup_founder, small_business_owner, ecommerce_seller, agency, consumer, other) and category (developer_tools, ai_tools, productivity, finance, small_business, marketing, ecommerce, design, other).
Return JSON: {"items":[{"cluster_id":"...","label":"...","summary":"...","persona":"...","category":"..."}]}"""


def cluster_signals(conn: sqlite3.Connection, cluster_id: str, limit: int = 12) -> list[dict]:
    rows = conn.execute(
        """
        SELECT s.id, s.external_id, s.title, s.content, s.url, s.source_id, s.author, s.created_at, s.engagement_json, s.origin
        FROM pain_cluster_items pci JOIN signals s ON s.id=pci.signal_id WHERE pci.cluster_id=?
        ORDER BY pci.similarity DESC LIMIT ?
        """,
        (cluster_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def label_clusters(
    conn: sqlite3.Connection,
    *,
    min_signals: int = 2,
    batch: int = 8,
    job_id: str | None = None,
    only_ids: list[str] | None = None,
) -> int:
    where = "label_source='rule' AND signal_count>=?"
    params: list = [min_signals]
    if only_ids:
        where += f" AND id IN ({','.join('?' * len(only_ids))})"
        params += only_ids
    rows = conn.execute(
        f"SELECT id, data_mode FROM pain_clusters WHERE {where} ORDER BY signal_count DESC LIMIT 60", params
    ).fetchall()
    labeled = 0
    for mode in ("live", "mock", "mixed"):
        group = [r for r in rows if r["data_mode"] == mode]
        if not group:
            continue
        provider = resolve_llm("FAST_MODEL", "mock" if mode == "mock" else "live")
        if provider is None:
            continue
        for start in range(0, len(group), batch):
            chunk = group[start : start + batch]
            payload = {
                "clusters": [
                    {
                        "id": r["id"],
                        "signals": [
                            {
                                "external_id": s["external_id"],
                                "title": s["title"],
                                "content": s["content"][:400],
                            }
                            for s in cluster_signals(conn, r["id"], 6)
                        ],
                    }
                    for r in chunk
                ]
            }
            try:
                data, model = provider.chat_json(
                    "FAST_MODEL",
                    LABEL_SYSTEM,
                    json.dumps(payload, ensure_ascii=False),
                    task="label_clusters",
                    conn=conn,
                    job_id=job_id,
                )
            except Exception as exc:
                log.warning("label_clusters failed: %s", exc)
                continue
            allowed = {r["id"] for r in chunk}
            for item in data.get("items", []) if isinstance(data, dict) else []:
                cid = item.get("cluster_id")
                if cid not in allowed or not item.get("label"):
                    continue
                conn.execute(
                    "UPDATE pain_clusters SET label=?, summary=COALESCE(?,summary), persona=COALESCE(?,persona), category=COALESCE(?,category), label_source=?, updated_at=? WHERE id=?",
                    (
                        str(item["label"])[:200],
                        item.get("summary"),
                        item.get("persona"),
                        item.get("category"),
                        "fixture" if model == "fixture" else model,
                        iso(utcnow()),
                        cid,
                    ),
                )
                labeled += 1
            conn.commit()
    return labeled
