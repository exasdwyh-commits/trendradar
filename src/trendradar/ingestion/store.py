"""Persist RawSignal / RawProduct with dedup layers 1–3 (canonical URL, content hash, simhash).
Layer 4 (semantic) runs after embeddings in clustering/dedup_semantic.py."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

from ..core.ids import stable_id
from ..core.timeutil import iso
from ..normalize import (
    canonicalize_url,
    clean_text,
    content_hash,
    detect_lang,
    hamming,
    rule_score,
    simhash64,
    to_signed,
)
from ..sources.base import RawProduct, RawSignal
from ..sources.producthunt.mapping import domain_of

SIMHASH_MAX_DISTANCE = (
    7  # 64-bit simhash over ~50-word texts: one extra word flips ~6 bits, distinct texts sit ≥ 15 apart
)


@dataclass
class StoreStats:
    seen: int = 0
    inserted: int = 0
    duplicates: int = 0
    filtered: int = 0
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "seen": self.seen,
            "inserted": self.inserted,
            "duplicates": self.duplicates,
            "filtered": self.filtered,
        }


def _find_duplicate(
    conn: sqlite3.Connection, canonical: str, chash: str, sim: int, source_id: str, origin: str
) -> str | None:
    """Layers 1–3 of dedup, always within the same origin: live data is never merged with demo fixtures."""
    row = conn.execute(
        "SELECT id FROM signals WHERE canonical_url=? AND source_id!=? AND origin=? LIMIT 1",
        (canonical, source_id, origin),
    ).fetchone()
    if row:
        return row["id"]
    row = conn.execute(
        "SELECT id FROM signals WHERE content_hash=? AND origin=? LIMIT 1", (chash, origin)
    ).fetchone()
    if row:
        return row["id"]
    # Near-duplicate: compare against recent signals' simhash (bounded scan; fine for V1 volumes).
    if not sim:  # too short to fingerprint — only exact matches count
        return None
    for cand in conn.execute(
        "SELECT id, simhash FROM signals WHERE simhash IS NOT NULL AND simhash != 0 AND origin=? "
        "ORDER BY fetched_at DESC LIMIT 5000",
        (origin,),
    ):
        other = cand["simhash"] + (1 << 64) if cand["simhash"] < 0 else cand["simhash"]
        if hamming(sim, other) <= SIMHASH_MAX_DISTANCE:
            return cand["id"]
    return None


def store_signal(conn: sqlite3.Connection, signal: RawSignal, *, min_rule_score: float = 0.0) -> str:
    """Insert one signal. Returns 'inserted' | 'duplicate' | 'exists'."""
    signal_id = stable_id(signal.source, signal.external_id)
    if conn.execute("SELECT 1 FROM signals WHERE id=?", (signal_id,)).fetchone():
        return "exists"
    title = clean_text(signal.title)[:400]
    content = clean_text(signal.content)[:8000]
    canonical = canonicalize_url(signal.url)
    chash = content_hash(title, content)
    sim = simhash64(f"{title} {content}")
    dup_of = _find_duplicate(conn, canonical, chash, sim, signal.source, signal.origin)
    score, matched = rule_score(title, content)
    status = "duplicate" if dup_of else ("filtered" if score < min_rule_score else "new")
    metadata = dict(signal.metadata)
    metadata["rule_matches"] = matched
    conn.execute(
        """
        INSERT INTO signals(id,source_id,adapter,external_id,url,canonical_url,title,content,author,author_id,lang,
          created_at,fetched_at,engagement_json,metadata_json,content_hash,simhash,origin,dedup_of,rule_score,status)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            signal_id,
            signal.source,
            signal.adapter,
            signal.external_id,
            signal.url,
            canonical,
            title,
            content,
            signal.author,
            signal.author_id,
            detect_lang(f"{title} {content}"),
            iso(signal.created_at),
            iso(signal.fetched_at),
            signal.engagement.model_dump_json(),
            json.dumps(metadata, ensure_ascii=False, default=str),
            chash,
            to_signed(sim),
            signal.origin,
            dup_of,
            score,
            status,
        ),
    )
    return "duplicate" if dup_of else "inserted"


def store_product(conn: sqlite3.Connection, product: RawProduct) -> str:
    product_id = stable_id(product.source, product.external_id)
    domain = domain_of(product.website)
    alias_of = None
    if domain:
        row = conn.execute(
            "SELECT id FROM products WHERE domain=? AND id!=? AND alias_of IS NULL LIMIT 1",
            (domain, product_id),
        ).fetchone()
        if row:
            alias_of = row["id"]
    conn.execute(
        """
        INSERT INTO products(id,source_id,adapter,external_id,name,slug,tagline,description,url,website,domain,categories_json,
          votes,comments,rating,review_count,launched_at,makers_json,credibility_json,pricing,pricing_origin,origin,alias_of,raw_json,fetched_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(source_id, external_id) DO UPDATE SET
          name=excluded.name,tagline=excluded.tagline,description=excluded.description,votes=excluded.votes,
          comments=excluded.comments,rating=excluded.rating,review_count=excluded.review_count,categories_json=excluded.categories_json,
          raw_json=excluded.raw_json,fetched_at=excluded.fetched_at,pricing=COALESCE(products.pricing,excluded.pricing)
        """,
        (
            product_id,
            product.source,
            product.adapter,
            product.external_id,
            product.name[:200],
            product.slug,
            (product.tagline or "")[:400],
            clean_text(product.description)[:4000] or None,
            product.url,
            product.website,
            domain,
            json.dumps(product.categories, ensure_ascii=False),
            product.votes,
            product.comments,
            product.rating,
            product.review_count,
            iso(product.launched_at),
            json.dumps(product.makers, ensure_ascii=False, default=str),
            json.dumps(product.credibility, ensure_ascii=False, default=str),
            product.pricing,
            product.pricing_origin,
            product.origin,
            alias_of,
            json.dumps(
                {**product.raw, "comment_samples": product.comment_samples}, ensure_ascii=False, default=str
            )[:20000],
            iso(product.fetched_at),
        ),
    )
    if alias_of:
        conn.execute(
            "INSERT OR IGNORE INTO edges(id,from_type,from_id,relation,to_type,to_id) VALUES(?,?,?,?,?,?)",
            (
                stable_id("edge", product_id, "alias_of", alias_of),
                "product",
                product_id,
                "alias_of",
                "product",
                alias_of,
            ),
        )
    return "upserted"
