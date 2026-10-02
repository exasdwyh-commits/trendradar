"""Embedding providers. Vectors are stored per (model, dim) so switching providers never mixes spaces."""

from __future__ import annotations

import hashlib
import math
import sqlite3
import time
from typing import Protocol

import httpx
import numpy as np

from ..core.errors import NotConfigured
from ..core.settings import model_environment
from ..normalize.text import tokens
from .llm import _enforce_budget, load_slot, log_ai_run

EMBEDDING_SLOT = "EMBEDDING_MODEL"


class EmbeddingProvider(Protocol):
    name: str
    dim: int
    degraded: bool

    def embed(
        self, texts: list[str], *, conn: sqlite3.Connection | None = None, task: str = "embed"
    ) -> np.ndarray: ...


class LocalHashEmbedding:
    """Deterministic hashed unigram+bigram TF vectors (no network, no model download).

    Good enough to demo clustering offline; clearly weaker than a real embedding model, so anything
    built on it is flagged degraded and recomputed when EMBEDDING_MODEL becomes available.
    """

    name = "local-hash-512"
    dim = 512
    degraded = True

    @staticmethod
    def _stem(tok: str) -> str:
        for suffix in ("ing", "ers", "er", "ies", "es", "ed", "ly", "s"):
            if len(tok) > len(suffix) + 3 and tok.endswith(suffix):
                return tok[: -len(suffix)] + ("y" if suffix == "ies" else "")
        return tok

    def _vec(self, text: str) -> np.ndarray:
        # Unsigned hashing keeps cosine an overlap measure (like TF cosine) instead of cancelling out;
        # light stemming raises overlap between "session"/"sessions", "agent"/"agents".
        v = np.zeros(self.dim, dtype=np.float32)
        toks = [self._stem(t) for t in tokens(text)]
        counts: dict[str, float] = {}
        for t in toks:
            counts[t] = counts.get(t, 0.0) + 1.0
        for a, b in zip(toks, toks[1:], strict=False):
            counts[f"{a}_{b}"] = counts.get(f"{a}_{b}", 0.0) + 0.4
        for f, c in counts.items():
            h = hashlib.blake2b(f.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(h[:4], "big") % self.dim
            v[idx] += 1.0 + math.log(c) if c >= 1 else c
        norm = float(np.linalg.norm(v))
        return v / norm if norm > 0 else v

    def embed(self, texts: list[str], *, conn=None, task: str = "embed") -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.vstack([self._vec(t) for t in texts])


class OpenAICompatibleEmbedding:
    degraded = False

    def __init__(self, batch_size: int = 64, timeout: float = 60):
        slot = load_slot(EMBEDDING_SLOT)
        if not slot.enabled:
            raise NotConfigured("EMBEDDING_MODEL slot not configured")
        self.slot = slot
        self.name = slot.model
        self.dim = int(
            model_environment().get("EMBEDDING_MODEL_DIM", "0") or 0
        )  # learned from first response if 0
        self.batch_size = batch_size
        self.timeout = timeout

    def embed(self, texts: list[str], *, conn=None, task: str = "embed") -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim or 1), dtype=np.float32)
        url = (
            self.slot.base_url
            if self.slot.base_url.endswith("/embeddings")
            else self.slot.base_url + "/embeddings"
        )
        headers = {"Authorization": f"Bearer {self.slot.api_key}", "Content-Type": "application/json"}
        out: list[np.ndarray] = []
        with httpx.Client(timeout=self.timeout) as client:
            for start in range(0, len(texts), self.batch_size):
                batch = [t[:6000] for t in texts[start : start + self.batch_size]]
                _enforce_budget(conn, self.slot)
                started = time.perf_counter()
                last_error = ""
                for attempt in range(1, 4):
                    try:
                        response = client.post(
                            url, headers=headers, json={"model": self.slot.model, "input": batch}
                        )
                        if response.status_code == 429 or response.status_code >= 500:
                            raise httpx.HTTPStatusError(
                                "transient", request=response.request, response=response
                            )
                        response.raise_for_status()
                        data = response.json()
                        rows = sorted(data["data"], key=lambda d: d.get("index", 0))
                        vecs = np.array([r["embedding"] for r in rows], dtype=np.float32)
                        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
                        vecs = (vecs / np.where(norms == 0, 1, norms)).astype(np.float32, copy=False)
                        if not self.dim:
                            self.dim = int(vecs.shape[1])
                        usage = data.get("usage") or {}
                        it = int(usage.get("prompt_tokens") or usage.get("total_tokens") or 0)
                        log_ai_run(
                            conn,
                            task=task,
                            slot=EMBEDDING_SLOT,
                            model=self.slot.model,
                            input_tokens=it,
                            cost=it / 1e6 * self.slot.input_cny_per_million,
                            duration_ms=int((time.perf_counter() - started) * 1000),
                            ok=True,
                            attempts=attempt,
                        )
                        out.append(vecs)
                        break
                    except (httpx.TransportError, httpx.HTTPStatusError, KeyError, ValueError) as exc:
                        last_error = f"{type(exc).__name__}: {exc}"
                        if attempt == 3:
                            log_ai_run(
                                conn,
                                task=task,
                                slot=EMBEDDING_SLOT,
                                model=self.slot.model,
                                ok=False,
                                error=last_error,
                                attempts=attempt,
                            )
                            raise RuntimeError(f"embedding failed: {last_error}") from exc
                        time.sleep(2**attempt)
        return np.vstack(out)


_override: EmbeddingProvider | None = None


def set_embedder(provider: EmbeddingProvider | None) -> None:
    global _override
    _override = provider


def get_embedder() -> EmbeddingProvider:
    if _override is not None:
        return _override
    if load_slot(EMBEDDING_SLOT).enabled:
        return OpenAICompatibleEmbedding()
    return LocalHashEmbedding()


def embedding_status() -> dict:
    provider = get_embedder()
    return {"provider": provider.name, "dim": provider.dim, "degraded": provider.degraded}


# ── vector (de)serialisation ──


def to_blob(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def from_blob(blob: bytes, dim: int) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32, count=dim)
