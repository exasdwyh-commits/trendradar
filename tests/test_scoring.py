from trendradar.scoring import (
    DimensionScore,
    competition_score,
    demand_score,
    final_score,
    judgement_dimension,
)


def test_no_competition_is_not_automatically_good():
    none = competition_score(
        competitor_count=0, density=0, maturity=0, avg_rating=None, complaint_count=0, evidence_ids=[]
    )
    some = competition_score(
        competitor_count=3, density=30, maturity=40, avg_rating=4.0, complaint_count=3, evidence_ids=["p1"]
    )
    crowded = competition_score(
        competitor_count=8, density=90, maturity=90, avg_rating=4.6, complaint_count=0, evidence_ids=["p1"]
    )
    assert some.score > none.score > crowded.score
    assert none.confidence < some.confidence


def test_demand_grows_with_independent_evidence():
    small = demand_score(signal_count=3, unique_users=2, source_count=1, engagement_total=10, evidence_ids=[])
    big = demand_score(
        signal_count=12, unique_users=12, source_count=3, engagement_total=800, evidence_ids=[]
    )
    assert 0 <= small.score < big.score <= 100


def test_final_score_is_weighted_and_confidence_damped():
    dims = {
        k: DimensionScore(k, 80, "r", 0.7)
        for k in (
            "pain",
            "demand",
            "growth",
            "competition",
            "gap",
            "monetization",
            "build_ease",
            "distribution",
        )
    }
    dims["confidence"] = DimensionScore("confidence", 100, "r", 1.0)
    full, _ = final_score(dims)
    dims["confidence"] = DimensionScore("confidence", 0, "r", 1.0)
    damped, _ = final_score(dims)
    assert full == 80.0 and damped == 56.0


def test_judgement_dimension_marks_unavailable():
    d = judgement_dimension("gap", None, model_name=None)
    assert d.method == "unavailable" and d.confidence < 0.5
    d2 = judgement_dimension("gap", {"score": 91, "reason": "x", "evidence_ids": ["a"]}, model_name="fixture")
    assert d2.score == 91 and d2.method == "fixture"
