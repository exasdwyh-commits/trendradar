"""In-memory cosine index over vectors stored in SQLite (numpy brute force; fine for V1 volumes).
The table layout (id, model, dim, vector BLOB) is compatible with a later sqlite-vec / pgvector swap."""

from __future__ import annotations

import sqlite3

import numpy as np

from ..providers.embeddings import from_blob, to_blob


class VectorIndex:
    def __init__(self, ids: list[str], matrix: np.ndarray):
        self.ids = ids
        self.matrix = matrix if len(ids) else np.zeros((0, 1), dtype=np.float32)
        self._pos = {i: k for k, i in enumerate(ids)}

    @classmethod
    def load(
        cls, conn: sqlite3.Connection, table: str, model: str, *, ids: list[str] | None = None
    ) -> VectorIndex:
        key = "signal_id" if table == "signal_embeddings" else "product_id"
        if ids is not None:
            if not ids:
                return cls([], np.zeros((0, 1), dtype=np.float32))
            rows = []
            for start in range(0, len(ids), 500):
                chunk = ids[start : start + 500]
                rows.extend(
                    conn.execute(
                        f"SELECT {key} id, dim, vector FROM {table} WHERE model=? AND {key} IN ({','.join('?' * len(chunk))})",
                        (model, *chunk),
                    ).fetchall()
                )
        else:
            rows = conn.execute(
                f"SELECT {key} id, dim, vector FROM {table} WHERE model=?", (model,)
            ).fetchall()
        if not rows:
            return cls([], np.zeros((0, 1), dtype=np.float32))
        dim = int(rows[0]["dim"])
        matrix = np.vstack([from_blob(r["vector"], dim) for r in rows])
        return cls([r["id"] for r in rows], matrix)

    def __len__(self) -> int:
        return len(self.ids)

    def vector(self, item_id: str) -> np.ndarray | None:
        pos = self._pos.get(item_id)
        return self.matrix[pos] if pos is not None else None

    def search(
        self, query: np.ndarray, k: int = 10, *, exclude: set[str] | None = None
    ) -> list[tuple[str, float]]:
        if not len(self.ids):
            return []
        sims = self.matrix @ query
        order = np.argsort(-sims)
        out: list[tuple[str, float]] = []
        for pos in order:
            item_id = self.ids[int(pos)]
            if exclude and item_id in exclude:
                continue
            out.append((item_id, float(sims[int(pos)])))
            if len(out) >= k:
                break
        return out


def store_vectors(
    conn: sqlite3.Connection, table: str, model: str, ids: list[str], matrix: np.ndarray
) -> None:
    key = "signal_id" if table == "signal_embeddings" else "product_id"
    dim = int(matrix.shape[1]) if len(ids) else 0
    conn.executemany(
        f"INSERT OR REPLACE INTO {table}({key},model,dim,vector) VALUES(?,?,?,?)",
        [(item_id, model, dim, to_blob(matrix[i])) for i, item_id in enumerate(ids)],
    )


def normalize(vec: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm > 0 else vec


def centroid(matrix: np.ndarray) -> np.ndarray:
    return normalize(matrix.mean(axis=0)) if len(matrix) else matrix
