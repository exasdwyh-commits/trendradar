"""Explore: query → market map (pain clusters, existing products, gaps, opportunity draft).

Sources used, in order: signals already in the database (semantic search), live demand adapters
(on-demand search, when configured), local product index + supply adapters. Session-scoped clusters
keep Explore from polluting the global radar; an opportunity draft is only produced when the session
cluster passes the same evidence gate as the daily pipeline.
"""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..analysis import classify_pending
from ..clustering import cluster_pending_signals, embed_pending_signals, label_clusters
from ..clustering.index import VectorIndex, normalize
from ..clustering.pain_clusters import cluster_signals
from ..clustering.solution_clusters import embed_pending_products
from ..core.config import PipelineConfig, get_pipeline_config
from ..core.ids import new_id, stable_id
from ..core.logging import get_logger
from ..core.timeutil import iso, utcnow
from ..ingestion.store import store_signal
from ..market.competition import build_competition_profile, expand_supply, search_products
from ..opportunities.generator import analyze_cluster
from ..providers.embeddings import from_blob, get_embedder
from ..providers.llm import resolve_llm
from ..sources.base import BaseAdapter, SearchQuery

log = get_logger("explore")


def _search_adapter(adapter: BaseAdapter, query: SearchQuery):
    try:
        return adapter, adapter.search(query), None
    except Exception as exc:  # one flaky source must not kill the session
        return adapter, None, str(exc)


def run_explore(
    conn: sqlite3.Connection,
    query: str,
    *,
    adapters: list[BaseAdapter] | None = None,
    cfg: PipelineConfig | None = None,
    live: bool = True,
    max_signals: int = 60,
) -> dict:
    cfg = cfg or get_pipeline_config()
    embedder = get_embedder()
    session_id = new_id()
    conn.execute("INSERT INTO explore_sessions(id,query,status) VALUES(?,?,'running')", (session_id, query))
    conn.commit()
    adapters = adapters or []
    demand = [a for a in adapters if a.type == "demand" and (live or a.mode == "mock")]
    supply = [a for a in adapters if a.type == "supply" and (live or a.mode == "mock")]
    warnings: list[str] = []
    try:
        # 1. On-demand collection from demand sources.
        fetched_ids: list[str] = []
        new_count = 0
        sources_used: dict[str, dict] = {}
        if demand:
            sq = SearchQuery(text=query, limit=25, kind="pain", window_days=180)
            with ThreadPoolExecutor(max_workers=min(6, len(demand))) as pool:
                for future in as_completed([pool.submit(_search_adapter, a, sq) for a in demand]):
                    adapter, result, error = future.result()
                    if error or result is None:
                        warnings.append(f"{adapter.id}: {error}")
                        sources_used[adapter.id] = {"mode": adapter.mode, "ok": False, "error": error}
                        continue
                    n = 0
                    for signal in result.signals:
                        outcome = store_signal(conn, signal)
                        sid = stable_id(signal.source, signal.external_id)
                        if outcome in ("inserted", "exists"):
                            fetched_ids.append(sid)
                            n += 1
                        new_count += outcome == "inserted"
                    sources_used[adapter.id] = {"mode": adapter.mode, "ok": True, "signals": n}
            conn.commit()
        # 2. Semantic recall from what we already know.
        q_vec = normalize(embedder.embed([query])[0])
        index = VectorIndex.load(conn, "signal_embeddings", embedder.name)
        hits = index.search(q_vec, k=max_signals)
        abs_floor = 0.12 if embedder.name.startswith("local") else 0.3
        best_hit = hits[0][1] if hits else 0.0
        recalled = [sid for sid, sim in hits if sim >= max(abs_floor, 0.55 * best_hit)]
        # 3. Classify + embed anything new, then session-scope clustering over the union.
        if fetched_ids:
            classify_pending(conn, min_rule_score=cfg.rule_filter_min_score, signal_ids=fetched_ids)
            embed_pending_signals(conn, embedder, min_relevance=cfg.classifier_min_relevance)
        candidate_ids = list(dict.fromkeys(recalled + fetched_ids))[: max_signals * 2]
        stats = cluster_pending_signals(
            conn,
            embedder,
            threshold=cfg.cluster_threshold(embedder.name),
            session_id=session_id,
            signal_ids=candidate_ids,
        )
        cluster_rows = conn.execute(
            "SELECT * FROM pain_clusters WHERE session_id=? ORDER BY signal_count DESC", (session_id,)
        ).fetchall()
        label_clusters(conn, min_signals=1, only_ids=[c["id"] for c in cluster_rows])
        cluster_rows = conn.execute(
            "SELECT * FROM pain_clusters WHERE session_id=? ORDER BY signal_count DESC", (session_id,)
        ).fetchall()
        # 4. Supply side.
        if supply:
            expand_supply(conn, supply, query, limit=20)
            embed_pending_products(conn, embedder)
        products = search_products(conn, embedder, query, k=12)
        if products:
            products = [p for p in products if p["similarity"] >= max(0.1, 0.45 * products[0]["similarity"])]
        # 5. Relevance + gap analysis (deterministic): rank clusters by closeness to the query; coverage = how many
        #    products sit close to the cluster; complaints about those products are the concrete gap material.
        prod_threshold = 0.25 if embedder.name.startswith("local") else 0.45
        clusters_out = []
        for c in cluster_rows:
            sig = cluster_signals(conn, c["id"], 5)
            relevance = (
                float(q_vec @ normalize(from_blob(c["centroid"], len(q_vec))))
                if c["centroid"] is not None
                else 0.0
            )
            best_products: list[dict] = []
            complaints: list[str] = []
            if products:
                text = f"{c['label']}. {c['summary'] or ''} " + " ".join(s["title"] for s in sig)
                product_hits = search_products(conn, embedder, text, k=4)
                best_products = [
                    {"id": h["id"], "name": h["name"], "similarity": h["similarity"], "origin": h["origin"]}
                    for h in product_hits
                    if h["similarity"] >= prod_threshold * 0.6
                ]
                for h in best_products:
                    ins = conn.execute(
                        "SELECT complaints_json FROM product_insights WHERE product_id=?", (h["id"],)
                    ).fetchone()
                    if ins:
                        complaints.extend(json.loads(ins["complaints_json"] or "[]")[:2])
            close = sum(1 for h in best_products if h["similarity"] >= prod_threshold)
            coverage = "served" if close >= 2 else "underserved" if close == 1 else "unserved"
            clusters_out.append(
                {
                    "id": c["id"],
                    "label": c["label"],
                    "summary": c["summary"],
                    "persona": c["persona"],
                    "category": c["category"],
                    "signal_count": c["signal_count"],
                    "unique_users": c["unique_users"],
                    "source_count": c["source_count"],
                    "data_mode": c["data_mode"],
                    "relevance": round(relevance, 3),
                    "coverage": coverage,
                    "closest_products": best_products,
                    "complaints": complaints[:6],
                    "signals": [
                        {
                            "id": s["id"],
                            "title": s["title"],
                            "url": s["url"],
                            "source_id": s["source_id"],
                            "origin": s["origin"],
                            "excerpt": s["content"][:220],
                        }
                        for s in sig
                    ],
                }
            )
        clusters_out.sort(key=lambda x: -(x["relevance"] * (1 + 0.15 * min(int(x["signal_count"]), 10))))
        if clusters_out:
            top_rel = clusters_out[0]["relevance"]
            clusters_out = [x for x in clusters_out if x["relevance"] >= max(0.05, 0.3 * top_rel)]
        cluster_by_id = {c["id"]: c for c in cluster_rows}
        cluster_rows = [cluster_by_id[x["id"]] for x in clusters_out]
        # 6. Opportunity draft for the strongest cluster that passes the evidence gate.
        draft = None
        for c in cluster_rows:
            if int(c["signal_count"]) >= cfg.gate_min_signals and (
                int(c["source_count"]) >= cfg.gate_min_sources
                or int(c["signal_count"]) >= cfg.gate_min_signals * 2
            ):
                build_competition_profile(conn, embedder, c["id"], k=cfg.competitors_per_cluster)
                res = analyze_cluster(conn, c["id"], weights=cfg.weights, session_id=session_id)
                if res.get("ok"):
                    opp = conn.execute(
                        "SELECT id, title, core_pain, proposed_solution, wedge, opportunity_score, confidence, data_mode, generated_by FROM opportunities WHERE id=?",
                        (res["opportunity_id"],),
                    ).fetchone()
                    draft = dict(opp)
                else:
                    draft = {"unavailable": res.get("reason")}
                break
        # 7. Overview text (model or fixture) — grounded in counts only; nothing invented.
        data_mode = _data_mode([c["data_mode"] for c in cluster_rows] + [p["origin"] for p in products])
        overview = None
        provider = resolve_llm("FAST_MODEL", data_mode)
        if provider is not None:
            try:
                payload = {
                    "query": query,
                    "signal_count": sum(int(c["signal_count"]) for c in cluster_rows),
                    "product_count": len(products),
                    "clusters": [
                        {"label": c["label"], "signal_count": c["signal_count"], "coverage": x["coverage"]}
                        for c, x in zip(cluster_rows, clusters_out, strict=False)
                    ],
                    "products": [
                        {"name": p["name"], "tagline": p["tagline"], "votes": p["votes"]}
                        for p in products[:8]
                    ],
                }
                data, _ = provider.chat_json(
                    "FAST_MODEL",
                    EXPLORE_SYSTEM,
                    json.dumps(payload, ensure_ascii=False),
                    task="explore_overview",
                    conn=conn,
                )
                overview = (data.get("overview") if isinstance(data, dict) else None) or None
            except Exception as exc:
                warnings.append(f"overview: {exc}")
        result = {
            "session_id": session_id,
            "query": query,
            "data_mode": data_mode,
            "overview": overview,
            "sources": sources_used,
            "new_signals": new_count,
            "recalled_signals": len(recalled),
            "clusters": clusters_out,
            "products": [
                {
                    "id": p["id"],
                    "name": p["name"],
                    "tagline": p["tagline"],
                    "url": p["url"],
                    "votes": p["votes"],
                    "rating": p["rating"],
                    "pricing": p.get("pricing"),
                    "launched_at": p["launched_at"],
                    "similarity": p["similarity"],
                    "origin": p["origin"],
                }
                for p in products
            ],
            "gaps": [
                {
                    "cluster_id": c["id"],
                    "label": c["label"],
                    "coverage": c["coverage"],
                    "complaints": c["complaints"],
                }
                for c in clusters_out
                if c["coverage"] != "served" or c["complaints"]
            ],
            "opportunity_draft": draft,
            "cluster_stats": stats.as_dict(),
            "warnings": warnings,
            "created_at": iso(utcnow()),
        }
        conn.execute(
            "UPDATE explore_sessions SET status='done', result_json=? WHERE id=?",
            (json.dumps(result, ensure_ascii=False, default=str), session_id),
        )
        conn.commit()
        return result
    except Exception as exc:
        log.exception("explore failed")
        conn.execute(
            "UPDATE explore_sessions SET status='failed', error=? WHERE id=?", (str(exc)[:1000], session_id)
        )
        conn.commit()
        raise


EXPLORE_SYSTEM = """You write a 2–3 sentence neutral market overview for an opportunity radar. Use only the counts, cluster labels and product names given. Do not invent facts, numbers or products. Return JSON: {"overview": "..."}"""


def _data_mode(modes: list[str]) -> str:
    modes = [m for m in modes if m]
    if not modes:
        return "mock"
    if all(m == "mock" for m in modes):
        return "mock"
    if all(m == "live" for m in modes):
        return "live"
    return "mixed"


def load_explore(conn: sqlite3.Connection, session_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM explore_sessions WHERE id=?", (session_id,)).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "query": row["query"],
        "status": row["status"],
        "error": row["error"],
        "created_at": row["created_at"],
        "result": json.loads(row["result_json"] or "{}"),
    }


def cleanup_sessions(conn: sqlite3.Connection, keep: int = 50) -> int:
    ids = [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM explore_sessions ORDER BY created_at DESC LIMIT -1 OFFSET ?", (keep,)
        )
    ]
    for sid in ids:
        conn.execute("DELETE FROM opportunities WHERE session_id=?", (sid,))
        conn.execute("DELETE FROM pain_clusters WHERE session_id=?", (sid,))
        conn.execute("DELETE FROM explore_sessions WHERE id=?", (sid,))
    conn.commit()
    return len(ids)
