import json
from pathlib import Path

from trendradar.normalize.rules import rule_score
from trendradar.normalize.simhash import hamming, simhash64
from trendradar.normalize.text import content_hash, normalized_key
from trendradar.normalize.url import canonicalize_url

FIXTURES = Path(__file__).resolve().parents[1] / "src/trendradar/sources/mock/fixtures/demand_signals.json"


def test_canonicalize_url_strips_tracking_and_fragments():
    a = canonicalize_url("https://Example.com/post/1?utm_source=x&b=2&a=1#top")
    b = canonicalize_url("http://example.com/post/1/?a=1&b=2")
    assert a == b


def test_content_hash_ignores_case_and_whitespace():
    assert content_hash("Hello", "  World!") == content_hash("hello", "world")
    assert normalized_key("  Foo  bar ") == normalized_key("foo bar")


def test_simhash_near_duplicates_are_close():
    base = "I have three Claude Code sessions open and I constantly lose track of which agent is doing what in which repo"
    near = base + " today"
    far = "Best pizza recipe for a Saturday night with friends and family, cheese and tomatoes"
    assert hamming(simhash64(base), simhash64(near)) <= 7
    assert hamming(simhash64(base), simhash64(far)) > 10


def test_rule_score_separates_pain_from_noise_fixtures():
    rows = json.loads(FIXTURES.read_text())
    pains = [r for r in rows if r.get("case") != "noise"]
    noise = [r for r in rows if r.get("case") == "noise"]
    assert pains and noise
    for r in pains:
        score, labels = rule_score(r["title"], r["content"])
        assert score >= 0.15, (r["external_id"], score, labels)
    for r in noise:
        score, _ = rule_score(r["title"], r["content"])
        assert score < 0.15, (r["external_id"], score)


def test_simhash_handles_cjk_text_and_refuses_to_fingerprint_short_text():
    """Chinese/Japanese text has no whitespace word boundaries; character bigrams keep distinct
    stories apart (regression: every CJK item used to hash to 0 and was dropped as a near-duplicate)."""
    a = simhash64(
        "2026年8月份能源生产情况 - 国家统计局 8月份规模以上工业原煤、原油、天然气、电力生产同比增长"
    )
    b = simhash64("2026年1—8月份社会消费品零售总额增长1.1% - 国家统计局 1—8月份社会消费品零售总额同比增长")
    c = simhash64(
        "2026年8月份能源生产情况 - 国家统计局 8月份规模以上工业原煤、原油、天然气、电力生产同比增加"
    )
    assert a and b and a != b
    assert hamming(a, b) > 7
    assert hamming(a, c) <= 7
    assert simhash64("你好") == 0 and simhash64("hi there") == 0
