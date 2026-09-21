from pathlib import Path

from trendradar.config import load_sources

ROOT = Path(__file__).resolve().parents[1]


def test_only_business_lanes_exist():
    sources = load_sources(ROOT / "config" / "sources.yml")
    assert {s.lane for s in sources} <= {
        "COMPANY","INDUSTRY","BUSINESS_MODEL","AI_COMMERCIALIZATION","GLOBALIZATION"
    }


def test_no_hotlist_sources():
    forbidden = {"weibo","douyin","toutiao","baidu","bilibili","tieba","zhihu"}
    ids = {s.id for s in load_sources(ROOT / "config" / "sources.yml")}
    assert not (ids & forbidden)


def test_each_enabled_lane_has_primary_or_verifier():
    sources = [s for s in load_sources(ROOT / "config" / "sources.yml") if s.enabled]
    for lane in {s.lane for s in sources}:
        assert any(s.lane == lane and s.role in {"PRIMARY","VERIFIER"} for s in sources)
