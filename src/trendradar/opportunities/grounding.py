"""Grounding helpers: model output must point at things that exist in our database."""

from __future__ import annotations

import re


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def ground_quote(quote: str | None, source_text: str, *, min_len: int = 12) -> tuple[str | None, bool]:
    """Return (quote, grounded). A quote is grounded only if it appears verbatim (after light
    normalisation) in the source text. Ungrounded quotes are dropped, never displayed as real."""
    if not quote or len(quote.strip()) < min_len:
        return None, False
    q = _norm(quote)
    if q and q in _norm(source_text):
        return quote.strip()[:400], True
    # try longest sentence fragment of the quote
    for frag in re.split(r"[.!?;\n]", quote):
        f = _norm(frag)
        if len(f) >= 25 and f in _norm(source_text):
            return frag.strip()[:400], True
    return None, False


def keep_known_ids(ids: list[str] | None, allowed: set[str]) -> list[str]:
    return [i for i in (ids or []) if i in allowed][:8]
