from __future__ import annotations

import hashlib
import uuid


def stable_id(*parts: str, length: int = 24) -> str:
    """Deterministic id from parts — the same input always yields the same id (idempotent upserts)."""
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:length]


def new_id() -> str:
    return uuid.uuid4().hex
