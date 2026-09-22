from __future__ import annotations

import re


NUMERIC_CLAIM_RE = re.compile(
    r"""
    (?:
      [$¥€£]\s?\d[\d,]*(?:\.\d+)?
      |
      \d+(?:\.\d+)?\s*
      (?:
        %|％|倍|x|X|
        亿美元|万美元|美元|元|
        亿元|万元|亿|万|
        billion|million|trillion|bn|mn|
        users?|customers?|employees?|stores?|factories?|contracts?
      )
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def numeric_claim_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for match in NUMERIC_CLAIM_RE.finditer(text or ""):
        token = re.sub(r"\s+|,", "", match.group(0)).lower()
        if token:
            tokens.add(token)
    return tokens


def unsupported_numeric_claims(generated: str, allowed_texts: list[str]) -> set[str]:
    generated_tokens = numeric_claim_tokens(generated)
    allowed: set[str] = set()
    for text in allowed_texts:
        allowed.update(numeric_claim_tokens(text or ""))
    return generated_tokens - allowed


def assert_no_new_numeric_claims(
    generated: str,
    allowed_texts: list[str],
    *,
    context: str,
) -> None:
    unsupported = unsupported_numeric_claims(generated,allowed_texts)
    if unsupported:
        values = ", ".join(sorted(unsupported))
        raise ValueError(f"{context} introduced unsupported numeric claims: {values}")
