from trendradar.grounding import (
    assert_no_new_numeric_claims,
    numeric_claim_tokens,
    unsupported_numeric_claims,
)


def test_numeric_claim_guard_allows_existing_business_metric():
    allowed=["Revenue grew 35% and contract value reached $50 million."]
    generated="收入增长35%，合同价值仍为$50 million。"
    assert unsupported_numeric_claims(generated,allowed) == set()


def test_numeric_claim_guard_blocks_new_metric():
    allowed=["Revenue grew 35%."]
    generated="Revenue grew 80%."
    assert unsupported_numeric_claims(generated,allowed) == {"80%"} 


def test_numeric_claim_guard_ignores_plain_outline_numbers():
    assert numeric_claim_tokens("1. 发生了什么\n2. 为什么现在\n2026年的变化") == set()


def test_numeric_claim_guard_raises_with_context():
    try:
        assert_no_new_numeric_claims(
            "客户成本下降60%",
            ["客户反馈成本下降20%"],
            context="writer",
        )
    except ValueError as exc:
        assert "writer" in str(exc)
        assert "60%" in str(exc)
    else:
        raise AssertionError("expected grounding guard to fail")
