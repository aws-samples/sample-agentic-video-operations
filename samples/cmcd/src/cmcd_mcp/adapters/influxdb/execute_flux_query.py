"""Execute a caller-supplied read-only Flux query."""

import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from media_ops_contracts.tool_failure import FailureKind, ToolFailure

_SIDE_EFFECT = re.compile(r"(?i)(?:^|[|>\s])(?:[a-z_][\w]*\.)*(?:to|post|write)\s*\(")
_ASSIGNMENT = re.compile(r"(?<![=!<>])=(?![=>~])")


class FluxQueryResult(BaseModel):
    records: list[dict[str, Any]]
    record_count: int


def execute_flux_query(
    flux: str,
    *,
    query_influxdb: Callable[[str], list[dict[str, Any]]],
) -> FluxQueryResult:
    """Return records for an explicit Flux query."""
    _require_read_only_flux(flux)
    records = query_influxdb(flux)
    return FluxQueryResult(records=records, record_count=len(records))


def _require_read_only_flux(flux: str) -> None:
    normalized = re.sub(r"//.*?$|/\*.*?\*/", "", flux, flags=re.MULTILINE | re.DOTALL)
    if not normalized.strip():
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            "The Flux query is empty.",
            "Provide a read query for the cmcd-metrics bucket.",
        )
    if (
        re.search(r"(?im)^\s*import\b", normalized)
        or _ASSIGNMENT.search(normalized)
        or _SIDE_EFFECT.search(normalized)
    ):
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            "The raw Flux tool accepts read-only queries only.",
            "Remove imports, variable assignments, and write or network-output functions.",
        )
