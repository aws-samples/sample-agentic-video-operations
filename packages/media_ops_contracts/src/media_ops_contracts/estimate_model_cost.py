"""Estimated USD cost of a Bedrock model invocation, from its token usage.

The rates below could not be confirmed through the AWS Price List API or the
public pricing page on the date recorded here. The result is visibility for a
sample, not billing data.
"""

from datetime import date

BEDROCK_PRICING_URL = "https://aws.amazon.com/bedrock/pricing/"
PRICING_CHECKED_ON = date(2026, 10, 6)
COST_ESTIMATE_BASIS = (
    "estimated list price, in-region on-demand, cache reads at 0.1x and writes at 1.25x the "
    "input rate, excludes cross-region differences"
)
# Bedrock reports cached input apart from inputTokens. Anthropic models bill a cache read at
# a tenth of the input rate and a five-minute cache write at one and a quarter times it.
CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_MULTIPLIER = 1.25
RATES_CONFIRMED = False

# Exact canonical IDs from scripts/model_ids.py -> USD per million (input, output) tokens.
_USD_PER_MILLION_TOKENS = {
    "us.anthropic.claude-sonnet-4-6": (3.00, 15.00),
    "anthropic.claude-sonnet-4-6": (3.00, 15.00),
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": (1.00, 5.00),
    "global.anthropic.claude-haiku-4-5-20251001-v1:0": (1.00, 5.00),
}
PRICED_MODEL_IDS = frozenset(_USD_PER_MILLION_TOKENS)


def estimate_model_cost_usd(
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    *,
    cache_read_input_tokens: int = 0,
    cache_write_input_tokens: int = 0,
) -> float | None:
    """Return the estimated cost, or None when the exact model ID is not in the table."""
    rates = _USD_PER_MILLION_TOKENS.get(model_id)
    if rates is None:
        return None
    input_rate, output_rate = rates
    cost = (
        input_tokens * input_rate
        + output_tokens * output_rate
        + cache_read_input_tokens * input_rate * CACHE_READ_MULTIPLIER
        + cache_write_input_tokens * input_rate * CACHE_WRITE_MULTIPLIER
    ) / 1_000_000
    return round(cost, 6)
