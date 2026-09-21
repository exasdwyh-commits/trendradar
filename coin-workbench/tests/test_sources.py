from pathlib import Path

from coinworkbench.config import load_sources
from coinworkbench.scoring import high_confidence_allowed


ROOT = Path(__file__).resolve().parents[1]


def test_all_four_lanes_have_sources():
    sources = load_sources(ROOT / "config" / "sources.yml")
    lanes = {s.lane for s in sources if s.enabled}
    assert lanes == {"TECHNOLOGY", "BUSINESS", "LIVELIHOOD", "SOCIETY"}


def test_every_lane_has_primary_source():
    sources = load_sources(ROOT / "config" / "sources.yml")
    for lane in {"TECHNOLOGY", "BUSINESS", "LIVELIHOOD", "SOCIETY"}:
        assert any(s.enabled and s.lane == lane and s.role == "PRIMARY" for s in sources)


def test_discovery_alone_never_supports_high_confidence():
    assert high_confidence_allowed({"DISCOVERY"}) is False
    assert high_confidence_allowed({"DISCOVERY", "VERIFIER"}) is True
    assert high_confidence_allowed({"PRIMARY"}) is True


def test_source_ids_unique():
    sources = load_sources(ROOT / "config" / "sources.yml")
    ids = [s.id for s in sources]
    assert len(ids) == len(set(ids))
