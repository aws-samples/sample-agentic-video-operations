"""Estimated USD cost of a Bedrock model invocation, from its token usage.

The rates below could not be confirmed through the AWS Price List API or the
public pricing page on the date recorded here. The result is visibility for a
sample, not billing data.
"""

from datetime import date

BEDROCK_PRICING_URL = "https://aws.amazon.com/bedrock/pricing/"
PRICING_CHECKED_ON = date(2026, 10, 6)
COST_ESTIMATE_BASIS = (
    "estimated list price, in-region on-demand, excludes caching and cross-region differences"
)
RATES_CONFIRMED = False

# Exact canonical IDs from scripts/model_ids.py -> USD per million (input, output) tokens.
_USD_PER_MILLION_TOKENS = {
    "us.anthropic.claude-sonnet-4-6": (3.00, 15.00),
    "anthropic.claude-sonnet-4-6": (3.00, 15.00),
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": (1.00, 5.00),
    "global.anthropic.claude-haiku-4-5-20251001-v1:0": (1.00, 5.00),
}
PRICED_MODEL_IDS = frozenset(_USD_PER_MILLION_TOKENS)


def estimate_model_cost_usd(model_id: str, input_tokens: int, output_tokens: int) -> float | None:
    """Return the estimated cost, or None when the exact model ID is not in the table."""
    rates = _USD_PER_MILLION_TOKENS.get(model_id)
    if rates is None:
        return None
    input_rate, output_rate = rates
    cost = (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
    return round(cost, 6)
