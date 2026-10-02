"""Offline, in-memory comparison of studio list queries before/after migration 7.

Run from the project root: python scripts/benchmark_studio.py --size 5000 --repeat 5
The benchmark uses synthetic data and never opens the application's database.
"""

from __future__ import annotations

import argparse
import json
from statistics import median
from time import perf_counter

from trendradar.db.connection import connect
from trendradar.db.migrate import available_migrations, migrate
from trendradar.studio.documents import list_documents
from trendradar.studio.materials import list_materials
from trendradar.studio.publishing import publish_center


def benchmark(size: int, repeat: int) -> dict:
    conn = connect(":memory:")
    try:
        for version, path in available_migrations():
            if version > 6:
                break
            conn.executescript(path.read_text(encoding="utf-8"))
            conn.execute(f"PRAGMA user_version={version}")
        conn.executemany(
            "INSERT INTO documents(id,title,status) VALUES(?,?,'ready')",
            [(f"d{i}", f"稿件 {i}") for i in range(size)],
        )
        conn.executemany(
            "INSERT INTO materials(id,kind,title,origin) VALUES(?,'note',?,'manual')",
            [(f"m{i}", f"素材 {i}") for i in range(size)],
        )
        conn.executemany(
            "INSERT INTO document_materials(document_id,material_id) VALUES(?,?)",
            [(f"d{i}", f"m{(i + j) % size}") for i in range(size) for j in range(min(10, size))],
        )
        conn.executemany(
            "INSERT INTO publications(id,document_id,platform) VALUES(?,?,'wechat')",
            [(f"p{i}-{j}", f"d{i}") for i in range(size) for j in range(5)],
        )
        conn.commit()
        queries = {"materials": list_materials, "documents": list_documents, "publish_center": publish_center}

        def measure() -> tuple[dict, dict]:
            timings, results = {}, {}
            for name, query in queries.items():
                results[name] = query(conn)  # warm the query before measuring
                samples = []
                for _ in range(repeat):
                    start = perf_counter()
                    query(conn)
                    samples.append((perf_counter() - start) * 1000)
                timings[name] = median(samples)
            return timings, results

        before, old_results = measure()
        migrate(conn)
        after, new_results = measure()
        if old_results != new_results:
            raise AssertionError("Index migration changed query results")
        return {
            "documents": size,
            "materials": size,
            "bindings": size * min(10, size),
            "publications": size * 5,
            "repeats": repeat,
            "results_unchanged": True,
            "median_ms": {
                name: {
                    "before": round(before[name], 3),
                    "after": round(after[name], 3),
                    "speedup": round(before[name] / after[name], 1),
                }
                for name in queries
            },
        }
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=2000)
    parser.add_argument("--repeat", type=int, default=5)
    args = parser.parse_args()
    if args.size < 1 or args.repeat < 1:
        parser.error("--size and --repeat must be positive")
    print(json.dumps(benchmark(args.size, args.repeat), indent=2, ensure_ascii=False))
