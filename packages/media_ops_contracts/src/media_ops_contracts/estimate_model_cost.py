"""Estimated USD cost of a Bedrock model invocation, from its token usage.

This answers "what did this turn cost me?" for demos and evals. It is an
estimate from a dated price table, not billing data: prices change, and the
table ignores prompt caching and batch discounts. Update the table from
https://aws.amazon.com/bedrock/pricing/ and move the date when you do.
"""

PRICING_VERIFIED_ON = "2026-10-06"

# base model id prefix -> (USD per million input tokens, USD per million output tokens)
_USD_PER_MILLION_TOKENS = {
    "anthropic.claude-sonnet-4-6": (3.00, 15.00),
    "anthropic.claude-haiku-4-5": (1.00, 5.00),
}

_REGION_PREFIXES = ("us.", "eu.", "apac.", "global.")


def estimate_model_cost_usd(model_id: str, input_tokens: int, output_tokens: int) -> float | None:
    """The estimated cost in USD, or None when the model is not in the table."""
    base_id = model_id
    for prefix in _REGION_PREFIXES:
        if base_id.startswith(prefix):
            base_id = base_id.removeprefix(prefix)
            break
    for known_prefix, (input_rate, output_rate) in _USD_PER_MILLION_TOKENS.items():
        if base_id.startswith(known_prefix):
            cost = (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
            return round(cost, 6)
    return None
