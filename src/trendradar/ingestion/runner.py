"""Concurrent collection across adapters with per-source health, then serialized SQLite writes."""

from __future__ import annotations

import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from ..core.logging import get_logger
from ..core.timeutil import iso, utcnow
from ..sources.base import BaseAdapter, FetchResult, SearchQuery
from .store import StoreStats, store_product, store_signal

log = get_logger("ingestion")


@dataclass
class CollectionStats:
    sources_ok: int = 0
    sources_failed: int = 0
    signals: StoreStats = field(default_factory=StoreStats)
    products: StoreStats = field(default_factory=StoreStats)
    failures: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    per_source: dict[str, dict] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "sources_ok": self.sources_ok,
            "sources_failed": self.sources_failed,
            "signals": self.signals.as_dict(),
            "products": self.products.as_dict(),
            "failures": self.failures,
            "warnings": self.warnings[:20],
            "per_source": self.per_source,
        }


def _health(
    conn: sqlite3.Connection, source_id: str, *, ok: bool, count: int, latency_ms: int, error: str | None
) -> None:
    now = iso(utcnow())
    if ok:
        conn.execute(
            """INSERT INTO source_health(source_id,last_attempt_at,last_success_at,last_error,consecutive_failures,last_item_count,latency_ms)
               VALUES(?,?,?,NULL,0,?,?)
               ON CONFLICT(source_id) DO UPDATE SET last_attempt_at=excluded.last_attempt_at,last_success_at=excluded.last_success_at,
               last_error=NULL,consecutive_failures=0,last_item_count=excluded.last_item_count,latency_ms=excluded.latency_ms""",
            (source_id, now, now, count, latency_ms),
        )
    else:
        conn.execute(
            """INSERT INTO source_health(source_id,last_attempt_at,last_error,consecutive_failures,last_item_count,latency_ms)
               VALUES(?,?,?,1,0,?)
               ON CONFLICT(source_id) DO UPDATE SET last_attempt_at=excluded.last_attempt_at,last_error=excluded.last_error,
               consecutive_failures=source_health.consecutive_failures+1,last_item_count=0,latency_ms=excluded.latency_ms""",
            (source_id, now, (error or "")[:500], latency_ms),
        )


def _fetch(
    adapter: BaseAdapter, query: SearchQuery | None
) -> tuple[BaseAdapter, FetchResult | None, str | None, int]:
    started = time.perf_counter()
    try:
        result = adapter.search(query) if query else adapter.fetch_latest()
        return adapter, result, None, int((time.perf_counter() - started) * 1000)
    except Exception as exc:  # adapters must never take the run down
        return (
            adapter,
            None,
            f"{type(exc).__name__}: {exc}"[:500],
            int((time.perf_counter() - started) * 1000),
        )


def persist(
    conn: sqlite3.Connection, result: FetchResult, stats: CollectionStats, *, min_rule_score: float
) -> None:
    for signal in result.signals:
        stats.signals.seen += 1
        outcome = store_signal(conn, signal, min_rule_score=min_rule_score)
        if outcome == "inserted":
            stats.signals.inserted += 1
        elif outcome == "duplicate":
            stats.signals.duplicates += 1
    for product in result.products:
        stats.products.seen += 1
        store_product(conn, product)
        stats.products.inserted += 1
    stats.warnings.extend(result.warnings)


def collect(
    conn: sqlite3.Connection,
    adapters: list[BaseAdapter],
    *,
    query: SearchQuery | None = None,
    max_workers: int = 6,
    min_rule_score: float = 0.0,
) -> CollectionStats:
    stats = CollectionStats()
    if not adapters:
        return stats
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(adapters)))) as pool:
        futures = [pool.submit(_fetch, a, query) for a in adapters]
        for future in as_completed(futures):
            adapter, result, error, latency = future.result()
            if error or result is None:
                stats.sources_failed += 1
                stats.failures.append({"source": adapter.id, "error": error})
                stats.per_source[adapter.id] = {"ok": False, "error": error, "latency_ms": latency}
                _health(conn, adapter.id, ok=False, count=0, latency_ms=latency, error=error)
                log.warning("source %s failed: %s", adapter.id, error)
            else:
                before = (stats.signals.inserted, stats.products.inserted)
                persist(conn, result, stats, min_rule_score=min_rule_score)
                stats.sources_ok += 1
                stats.per_source[adapter.id] = {
                    "ok": True,
                    "mode": adapter.mode,
                    "fetched": result.count,
                    "new_signals": stats.signals.inserted - before[0],
                    "products": stats.products.inserted - before[1],
                    "latency_ms": latency,
                }
                _health(conn, adapter.id, ok=True, count=result.count, latency_ms=latency, error=None)
            conn.commit()
    return stats
