"""Recognize CMCD numeric placeholders that do not represent measurements."""

from typing import Any

POSITIVE_VALUE_FIELDS = frozenset(
    {"cmcd_br", "cmcd_d", "cmcd_mtp", "cmcd_pr", "cmcd_rtp", "cmcd_tb", "cmcd_v"}
)


def is_missing_cmcd_metric(field: str, value: Any) -> bool:
    """Return true when a positive-only CMCD metric is absent, zero, or negative."""
    if field not in POSITIVE_VALUE_FIELDS:
        return False
    if value is None:
        return True
    try:
        return float(value) <= 0
    except (TypeError, ValueError):
        return False
