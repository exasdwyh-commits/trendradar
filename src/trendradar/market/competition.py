"""Supply-side analysis for a pain cluster:

  cluster label + top quotes → local semantic product search (+ adapter fallback) → top-N competitors
  → product insights (pros/cons/complaints derived from comments) → CompetitionProfile

Density/maturity are deterministic from the data; nothing here asks a model for a number.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import timedelta

from ..clustering.index import VectorIndex, normalize
from ..clustering.pain_clusters import cluster_signals
from ..clustering.solution_clusters import embed_pending_products
from ..core.ids import stable_id
from ..core.logging import get_logger
from ..core.timeutil import iso, parse_datetime, utcnow
from ..ingestion.store import store_product
from ..providers.embeddings import EmbeddingProvider
from ..providers.llm import resolve_llm
from ..sources.base import BaseAdapter, SearchQuery

log = get_logger("market")


# ───────────────────────── semantic product search ─────────────────────────


def search_products(
    conn: sqlite3.Connection,
    embedder: EmbeddingProvider,
    query_text: str,
    *,
    k: int = 8,
    min_similarity: float = 0.0,
    exclude_origin: str | None = None,
) -> list[dict]:
    index = VectorIndex.load(conn, "product_embeddings", embedder.name)
    if not len(index):
        return []
    q = normalize(embedder.embed([query_text])[0])
    hits = index.search(q, k=k * 3)
    out = []
    for pid, sim in hits:
        if sim < min_similarity:
            continue
        row = conn.execute("SELECT * FROM products WHERE id=? AND alias_of IS NULL", (pid,)).fetchone()
        if row is None or (exclude_origin and row["origin"] == exclude_origin):
            continue
        out.append({**dict(row), "similarity": round(sim, 4)})
        if len(out) >= k:
            break
    return out


def expand_supply(
    conn: sqlite3.Connection, adapters: list[BaseAdapter], query_text: str, *, limit: int = 20
) -> int:
    """On-demand supply fetch (Product Hunt topics / GitHub repos) to enrich the local corpus."""
    added = 0
    for adapter in adapters:
        if adapter.type != "supply":
            continue
        try:
            result = adapter.search(SearchQuery(text=query_text, limit=limit, kind="product"))
        except Exception as exc:  # never fail the pipeline because a supply source hiccupped
            log.warning("supply expansion via %s failed: %s", adapter.id, exc)
            continue
        for product in result.products:
            store_product(conn, product)
            added += 1
    conn.commit()
    return added


# ───────────────────────── product insights ─────────────────────────

INSIGHTS_SYSTEM = """You summarise user comments about software products for a market analyst.
For each product, using ONLY the provided comments, return pros (≤4 short phrases), cons (≤4), review_summary (1–2 sentences), complaints (≤4 concrete recurring complaints), pricing_guess (free|freemium|paid|open_source|unknown) and confidence 0-1. If comments are insufficient, say so in review_summary and keep lists short.
Return JSON: {"items":[{"product_id":"...","pros":[],"cons":[],"review_summary":"...","complaints":[],"pricing_guess":"unknown","confidence":0.5}]}"""


def ensure_product_insights(
    conn: sqlite3.Connection, product_ids: list[str], *, job_id: str | None = None
) -> int:
    todo = []
    for pid in product_ids:
        if conn.execute("SELECT 1 FROM product_insights WHERE product_id=?", (pid,)).fetchone():
            continue
        row = conn.execute(
            "SELECT id, external_id, name, tagline, description, origin, raw_json FROM products WHERE id=?",
            (pid,),
        ).fetchone()
        if row is None:
            continue
        comments = (json.loads(row["raw_json"] or "{}").get("comment_samples") or [])[:8]
        if not comments:
            continue
        todo.append((row, comments))
    if not todo:
        return 0
    written = 0
    for mode in ("live", "mock"):
        group = [(r, c) for r, c in todo if r["origin"] == mode]
        if not group:
            continue
        provider = resolve_llm("FAST_MODEL", mode)
        if provider is None:
            continue
        payload = {
            "products": [
                {
                    "id": r["id"],
                    "external_id": r["external_id"],
                    "name": r["name"],
                    "tagline": r["tagline"],
                    "comments": c,
                }
                for r, c in group[:10]
            ]
        }
        try:
            data, model = provider.chat_json(
                "FAST_MODEL",
                INSIGHTS_SYSTEM,
                json.dumps(payload, ensure_ascii=False),
                task="product_insights",
                conn=conn,
                job_id=job_id,
            )
        except Exception as exc:
            log.warning("product_insights failed: %s", exc)
            continue
        sample = {r["id"]: len(c) for r, c in group}
        for item in data.get("items", []) if isinstance(data, dict) else []:
            pid = item.get("product_id")
            if pid not in sample:
                continue
            conn.execute(
                """INSERT OR REPLACE INTO product_insights(product_id,pros_json,cons_json,review_summary,complaints_json,derived_from,sample_size,generated_by,confidence)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    pid,
                    json.dumps(item.get("pros") or [])[:2000],
                    json.dumps(item.get("cons") or [])[:2000],
                    (item.get("review_summary") or "")[:1000],
                    json.dumps(item.get("complaints") or [])[:2000],
                    "fixture" if model == "fixture" else "comments",
                    sample[pid],
                    model,
                    float(item.get("confidence") or 0.5),
                ),
            )
            guess = item.get("pricing_guess")
            if guess and guess != "unknown":
                conn.execute(
                    "UPDATE products SET pricing=COALESCE(pricing,?), pricing_origin=CASE WHEN pricing IS NULL THEN 'inferred' ELSE pricing_origin END WHERE id=?",
                    (guess, pid),
                )
            written += 1
        conn.commit()
    return written


# ───────────────────────── competition profile ─────────────────────────


def _maturity(competitors: list[dict]) -> float:
    if not competitors:
        return 0.0
    top_votes = max(int(c.get("votes") or 0) for c in competitors)
    ages = []
    for c in competitors:
        launched = parse_datetime(c.get("launched_at"))
        if launched:
            ages.append((utcnow() - launched).days)
    avg_age = sum(ages) / len(ages) if ages else 0
    paid_share = sum(1 for c in competitors if (c.get("pricing") or "") in ("paid", "freemium")) / len(
        competitors
    )
    score = min(40.0, top_votes / 25) + min(35.0, avg_age / 12) + paid_share * 25
    return round(min(100.0, score), 1)


def _density(competitors: list[dict]) -> float:
    n = len(competitors)
    recent = sum(
        1
        for c in competitors
        if (parse_datetime(c.get("launched_at")) or utcnow() - timedelta(days=9999))
        >= utcnow() - timedelta(days=90)
    )
    return round(min(100.0, n * 9 + recent * 6), 1)


def build_competition_profile(
    conn: sqlite3.Connection,
    embedder: EmbeddingProvider,
    cluster_id: str,
    *,
    adapters: list[BaseAdapter] | None = None,
    k: int = 8,
    job_id: str | None = None,
) -> dict | None:
    cluster = conn.execute("SELECT * FROM pain_clusters WHERE id=?", (cluster_id,)).fetchone()
    if cluster is None:
        return None
    signals = cluster_signals(conn, cluster_id, 4)
    query_text = f"{cluster['label']}. {cluster['summary'] or ''} " + " ".join(s["title"] for s in signals)
    if adapters and cluster["data_mode"] != "mock":
        expand_supply(conn, adapters, cluster["label"], limit=15)
        embed_pending_products(conn, embedder)
    exclude = "mock" if cluster["data_mode"] == "live" else None  # never pit live pains against demo products
    competitors = search_products(conn, embedder, query_text, k=k, exclude_origin=exclude)
    if cluster["data_mode"] == "mock":
        competitors = [c for c in competitors if c["origin"] == "mock"]
    # Keep only meaningful matches: relative threshold against the best hit.
    if competitors:
        best = competitors[0]["similarity"]
        competitors = [c for c in competitors if c["similarity"] >= max(0.05, best * 0.45)]
    ensure_product_insights(conn, [c["id"] for c in competitors], job_id=job_id)
    complaints: dict[str, int] = {}
    features: dict[str, int] = {}
    ratings = []
    reviews = 0
    pricing: dict[str, int] = {}
    for c in competitors:
        ins = conn.execute(
            "SELECT pros_json, complaints_json FROM product_insights WHERE product_id=?", (c["id"],)
        ).fetchone()
        if ins:
            for x in json.loads(ins["complaints_json"] or "[]"):
                complaints[x] = complaints.get(x, 0) + 1
            for x in json.loads(ins["pros_json"] or "[]"):
                features[x] = features.get(x, 0) + 1
        if c.get("rating") is not None:
            ratings.append(float(c["rating"]))
        reviews += int(c.get("review_count") or 0)
        pricing[c.get("pricing") or "unknown"] = pricing.get(c.get("pricing") or "unknown", 0) + 1
    recent = sum(
        1
        for c in competitors
        if (parse_datetime(c.get("launched_at")) or utcnow() - timedelta(days=9999))
        >= utcnow() - timedelta(days=90)
    )
    profile = {
        "id": stable_id("competition", cluster_id),
        "pain_cluster_id": cluster_id,
        "density": _density(competitors),
        "maturity": _maturity(competitors),
        "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
        "review_volume": reviews,
        "recent_launches_90d": recent,
        "competitor_count": len(competitors),
        "common_features": [k for k, _ in sorted(features.items(), key=lambda kv: -kv[1])[:8]],
        "common_complaints": [k for k, _ in sorted(complaints.items(), key=lambda kv: -kv[1])[:8]],
        "pricing_distribution": pricing,
        "competitors": [
            {
                "product_id": c["id"],
                "name": c["name"],
                "similarity": c["similarity"],
                "votes": c["votes"],
                "rating": c["rating"],
                "pricing": c.get("pricing"),
                "origin": c["origin"],
            }
            for c in competitors
        ],
        "data_mode": "mock"
        if competitors and all(c["origin"] == "mock" for c in competitors)
        else "live"
        if competitors and all(c["origin"] == "live" for c in competitors)
        else "mixed"
        if competitors
        else cluster["data_mode"],
    }
    conn.execute(
        """INSERT OR REPLACE INTO competition_profiles(id,pain_cluster_id,density,maturity,avg_rating,review_volume,recent_launches_90d,competitor_count,
           common_features_json,common_complaints_json,pricing_distribution_json,competitors_json,data_mode,computed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            profile["id"],
            cluster_id,
            profile["density"],
            profile["maturity"],
            profile["avg_rating"],
            profile["review_volume"],
            profile["recent_launches_90d"],
            profile["competitor_count"],
            json.dumps(profile["common_features"]),
            json.dumps(profile["common_complaints"]),
            json.dumps(profile["pricing_distribution"]),
            json.dumps(profile["competitors"]),
            profile["data_mode"],
            iso(utcnow()),
        ),
    )
    for c in competitors:
        conn.execute(
            "INSERT OR IGNORE INTO edges(id,from_type,from_id,relation,to_type,to_id,weight) VALUES(?,?,?,?,?,?,?)",
            (
                stable_id("edge", cluster_id, "solved_by", c["id"]),
                "pain_cluster",
                cluster_id,
                "solved_by",
                "product",
                c["id"],
                c["similarity"],
            ),
        )
    conn.commit()
    return profile


def load_competition_profile(conn: sqlite3.Connection, cluster_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM competition_profiles WHERE pain_cluster_id=?", (cluster_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    for key in ("common_features", "common_complaints", "pricing_distribution", "competitors"):
        d[key] = json.loads(d.pop(f"{key}_json") or ("{}" if key == "pricing_distribution" else "[]"))
    return d
