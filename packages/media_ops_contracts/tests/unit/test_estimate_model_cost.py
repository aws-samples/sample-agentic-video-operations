from media_ops_contracts.estimate_model_cost import (
    BEDROCK_PRICING_URL,
    COST_ESTIMATE_BASIS,
    PRICING_CHECKED_ON,
    RATES_CONFIRMED,
    estimate_model_cost_usd,
)


def test_sonnet_cost_uses_input_and_output_rates() -> None:
    # 1M input at $3 + 1M output at $15
    assert estimate_model_cost_usd("us.anthropic.claude-sonnet-4-6", 1_000_000, 1_000_000) == 18.0


def test_only_exact_canonical_model_ids_are_priced() -> None:
    canonical_ids = (
        "us.anthropic.claude-sonnet-4-6",
        "anthropic.claude-sonnet-4-6",
        "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    )
    assert all(estimate_model_cost_usd(model_id, 1, 1) is not None for model_id in canonical_ids)
    lookalike = "".join(("us.", "anthropic.claude-sonnet-4-6", "-new"))
    assert estimate_model_cost_usd(lookalike, 1, 1) is None


def test_haiku_small_turn_is_rounded_to_microdollars() -> None:
    # 2000 input at $1/M + 500 output at $5/M = 0.0045
    cost = estimate_model_cost_usd("us.anthropic.claude-haiku-4-5-20251001-v1:0", 2000, 500)
    assert cost == 0.0045


def test_unknown_model_returns_none() -> None:
    unknown = ".".join(("us", "amazon", "nova-pro-v1:0"))
    assert estimate_model_cost_usd(unknown, 1000, 1000) is None


def test_zero_tokens_cost_zero() -> None:
    assert estimate_model_cost_usd("us.anthropic.claude-sonnet-4-6", 0, 0) == 0.0


def test_the_estimate_is_dated_qualified_and_explicitly_unconfirmed() -> None:
    assert COST_ESTIMATE_BASIS == (
        "estimated list price, in-region on-demand, excludes caching and cross-region differences"
    )
    assert BEDROCK_PRICING_URL == "https://aws.amazon.com/bedrock/pricing/"
    assert PRICING_CHECKED_ON.isoformat() == "2026-10-06"
    assert RATES_CONFIRMED is False
