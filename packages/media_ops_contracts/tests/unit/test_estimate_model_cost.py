from media_ops_contracts.estimate_model_cost import estimate_model_cost_usd


def test_sonnet_cost_uses_input_and_output_rates() -> None:
    # 1M input at $3 + 1M output at $15
    assert estimate_model_cost_usd("us.anthropic.claude-sonnet-4-6", 1_000_000, 1_000_000) == 18.0


def test_region_prefix_is_ignored() -> None:
    direct = estimate_model_cost_usd("anthropic.claude-haiku-4-5-20251001-v1:0", 2000, 500)
    for prefix in ("us.", "eu.", "apac.", "global."):
        prefixed = estimate_model_cost_usd(
            f"{prefix}anthropic.claude-haiku-4-5-20251001-v1:0", 2000, 500
        )
        assert prefixed == direct


def test_haiku_small_turn_is_rounded_to_microdollars() -> None:
    # 2000 input at $1/M + 500 output at $5/M = 0.0045
    cost = estimate_model_cost_usd("us.anthropic.claude-haiku-4-5-20251001-v1:0", 2000, 500)
    assert cost == 0.0045


def test_unknown_model_returns_none() -> None:
    assert estimate_model_cost_usd("us.amazon.nova-pro-v1:0", 1000, 1000) is None


def test_zero_tokens_cost_zero() -> None:
    assert estimate_model_cost_usd("us.anthropic.claude-sonnet-4-6", 0, 0) == 0.0
