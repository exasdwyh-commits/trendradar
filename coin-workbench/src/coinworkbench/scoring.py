from __future__ import annotations

from datetime import datetime, timezone

ROLE_SCORE = {
    "PRIMARY": 100.0,
    "VERIFIER": 85.0,
    "DISCOVERY": 55.0,
}


def freshness_score(published_at: datetime | None, now: datetime | None = None) -> float:
    if published_at is None:
        return 45.0
    now = now or datetime.now(timezone.utc)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    hours = max(0.0, (now - published_at).total_seconds() / 3600)
    if hours <= 24:
        return 100.0
    if hours <= 48:
        return 85.0
    if hours <= 72:
        return 70.0
    if hours <= 168:
        return 50.0
    return 20.0


def evidence_score(role: str, has_body: bool, has_date: bool) -> float:
    base = ROLE_SCORE.get(role.upper(), 0.0)
    body_bonus = 0.0 if has_body else -15.0
    date_bonus = 0.0 if has_date else -10.0
    return max(0.0, min(100.0, base + body_bonus + date_bonus))


def high_confidence_allowed(roles: set[str]) -> bool:
    roles = {r.upper() for r in roles}
    return bool(roles & {"PRIMARY", "VERIFIER"})
