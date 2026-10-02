from __future__ import annotations

import hashlib

from .text import tokens

MIN_FEATURES = 6  # below this a 64-bit fingerprint is meaningless; return 0 = "no fingerprint"


def simhash64(text: str) -> int:
    """64-bit simhash over word tokens + bigrams (CJK text contributes character bigrams).
    Near-duplicates differ in few bits. Returns 0 when the text is too short to fingerprint;
    callers must treat 0 as "unknown", never as a match."""
    toks = tokens(text)
    feats = toks + [f"{a} {b}" for a, b in zip(toks, toks[1:], strict=False)]
    if len(feats) < MIN_FEATURES:
        return 0
    v = [0] * 64
    for f in feats:
        h = int.from_bytes(hashlib.blake2b(f.encode("utf-8"), digest_size=8).digest(), "big")
        for i in range(64):
            v[i] += 1 if (h >> i) & 1 else -1
    out = 0
    for i in range(64):
        if v[i] > 0:
            out |= 1 << i
    return out


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def to_signed(value: int) -> int:
    """SQLite INTEGER is signed 64-bit."""
    return value - (1 << 64) if value >= (1 << 63) else value


def from_signed(value: int) -> int:
    return value + (1 << 64) if value < 0 else value
