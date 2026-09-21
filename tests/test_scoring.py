from datetime import datetime, timedelta, timezone

from trendradar.scoring import commercial_score, evidence_score, freshness_score, high_confidence_allowed


def test_primary_beats_discovery():
    assert evidence_score("PRIMARY", True, True) > evidence_score("DISCOVERY", True, True)


def test_discovery_cannot_support_high_confidence_alone():
    assert not high_confidence_allowed({"DISCOVERY"})
    assert high_confidence_allowed({"VERIFIER"})


def test_business_signal_beats_generic_sentence():
    a = commercial_score("Startup wins $50 million enterprise contract and expands factory")
    b = commercial_score("A nice story from this week")
    assert a > b


def test_freshness_declines():
    now = datetime.now(timezone.utc)
    assert freshness_score(now - timedelta(hours=3), now) > freshness_score(now - timedelta(days=5), now)
