from datetime import datetime, timedelta, timezone

from coinworkbench.scoring import evidence_score, freshness_score


def test_primary_beats_discovery():
    assert evidence_score("PRIMARY", True, True) > evidence_score("DISCOVERY", True, True)


def test_missing_body_and_date_are_penalized():
    full = evidence_score("VERIFIER", True, True)
    thin = evidence_score("VERIFIER", False, False)
    assert thin < full


def test_freshness_declines_with_age():
    now = datetime.now(timezone.utc)
    assert freshness_score(now - timedelta(hours=5), now) > freshness_score(now - timedelta(days=5), now)
