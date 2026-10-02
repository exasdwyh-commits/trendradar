"""Explainable opportunity scoring. Every dimension returns score / reason / confidence / evidence ids.

Deterministic dimensions (demand, growth, competition, confidence) are computed from stored data.
Judgement dimensions (pain, gap, monetization, build_ease, distribution) come from the analysis model
with a written reason; when the model is unavailable they are marked as such and weighted down.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

SCORING_VERSION = "v1"

DEFAULT_WEIGHTS = {
    "pain": 0.15,
    "demand": 0.15,
    "growth": 0.10,
    "competition": 0.15,
    "gap": 0.15,
    "monetization": 0.10,
    "build_ease": 0.10,
    "distribution": 0.05,
}


@dataclass
class DimensionScore:
    dimension: str
    score: float
    reason: str
    confidence: float
    evidence_ids: list[str] = field(default_factory=list)
    method: str = "deterministic"

    def as_dict(self) -> dict:
        return {
            "dimension": self.dimension,
            "score": round(self.score, 1),
            "reason": self.reason,
            "confidence": round(self.confidence, 2),
            "evidence_ids": self.evidence_ids,
            "method": self.method,
        }


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


# ───────────────────────── deterministic dimensions ─────────────────────────


def demand_score(
    *, signal_count: int, unique_users: int, source_count: int, engagement_total: int, evidence_ids: list[str]
) -> DimensionScore:
    s = (
        14 * math.log1p(signal_count)
        + 8 * math.log1p(unique_users)
        + 6 * min(source_count, 4)
        + 4 * math.log1p(engagement_total / 50)
    )
    score = _clamp(s)
    reason = f"{signal_count} signals from {unique_users} distinct users across {source_count} source(s); combined engagement {engagement_total}."
    confidence = _clamp(35 + 12 * min(source_count, 4) + 3 * min(signal_count, 10), 0, 95) / 100
    return DimensionScore("demand", score, reason, confidence, evidence_ids[:6])


def growth_score(*, velocity: float, acceleration: float, stage: str, recent_7d: int) -> DimensionScore:
    base = {"emerging": 80, "growing": 65, "stable": 45, "new": 40, "fading": 20}.get(stage, 40)
    s = base + min(15, velocity * 3) + max(-10, min(10, acceleration * 4))
    reason = f"Stage {stage}: velocity ×{velocity:.1f} vs. prior 2-week baseline, acceleration {acceleration:+.1f}, {recent_7d} new signals in 7 days."
    confidence = 0.4 if recent_7d < 3 else 0.6 if recent_7d < 8 else 0.75
    return DimensionScore("growth", _clamp(s), reason, confidence)


def competition_score(
    *,
    competitor_count: int,
    density: float,
    maturity: float,
    avg_rating: float | None,
    complaint_count: int,
    evidence_ids: list[str],
) -> DimensionScore:
    """No competition is NOT automatically good: validation counts for 40%."""
    if competitor_count == 0:
        validation = 15.0
    elif competitor_count <= 2:
        validation = 55.0
    else:
        validation = 80.0 + min(15.0, maturity / 8)
    intensity = density * 0.6 + maturity * 0.4
    differentiation = (
        40.0 + min(45.0, complaint_count * 9) + (10.0 if avg_rating is not None and avg_rating < 4.0 else 0.0)
    )
    score = 0.40 * validation + 0.35 * (100 - intensity) + 0.25 * min(100.0, differentiation)
    reason = (
        f"{competitor_count} comparable product(s): market validation {'weak' if competitor_count == 0 else 'moderate' if competitor_count <= 2 else 'strong'}; "
        f"density {density:.0f}/100, maturity {maturity:.0f}/100; {complaint_count} recurring complaint(s) leave room to differentiate"
        + (f"; average rating {avg_rating:.1f}" if avg_rating is not None else "")
        + "."
    )
    confidence = 0.35 if competitor_count == 0 else 0.6 if competitor_count <= 3 else 0.75
    return DimensionScore("competition", _clamp(score), reason, confidence, evidence_ids[:6])


def evidence_confidence(
    *,
    signal_count: int,
    source_count: int,
    unique_users: int,
    days_since_last: float,
    data_mode: str,
    model_available: bool,
) -> DimensionScore:
    s = (
        25
        + 10 * min(source_count, 4)
        + 3 * min(signal_count, 12)
        + 2 * min(unique_users, 10)
        - min(20, days_since_last * 0.5)
    )
    if not model_available:
        s -= 15
    if data_mode == "mock":
        s = min(s, 70)
    reason = (
        f"{source_count} source type(s), {signal_count} signals, {unique_users} users, last signal {days_since_last:.0f}d ago"
        + ("; demo fixtures" if data_mode == "mock" else "")
        + ("; no analysis model — judgement dimensions unavailable" if not model_available else "")
        + "."
    )
    return DimensionScore("confidence", _clamp(s), reason, 1.0)


# ───────────────────────── judgement dimensions ─────────────────────────


def judgement_dimension(name: str, payload: dict | None, *, model_name: str | None) -> DimensionScore:
    if not payload or payload.get("score") is None:
        return DimensionScore(
            name,
            50.0,
            "No analysis model available — neutral placeholder, weighted down by confidence.",
            0.2,
            [],
            "unavailable",
        )
    try:
        score = _clamp(float(payload["score"]))
    except (TypeError, ValueError):
        score = 50.0
    return DimensionScore(
        name,
        score,
        str(payload.get("reason") or "")[:600],
        0.7 if model_name != "fixture" else 0.6,
        list(payload.get("evidence_ids") or [])[:6],
        "fixture" if model_name == "fixture" else "model",
    )


# ───────────────────────── final ─────────────────────────


def final_score(
    dimensions: dict[str, DimensionScore], weights: dict[str, float] | None = None
) -> tuple[float, float]:
    weights = weights or DEFAULT_WEIGHTS
    total_w = sum(weights.values()) or 1.0
    base = sum(weights[k] * dimensions[k].score for k in weights if k in dimensions) / total_w
    confidence = dimensions["confidence"].score if "confidence" in dimensions else 50.0
    final = base * (0.7 + 0.3 * confidence / 100)
    return round(final, 1), round(confidence, 1)
