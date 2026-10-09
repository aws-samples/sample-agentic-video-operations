"""The one boundary between delivery evidence and operator-facing failures.

An HTTP error status or transport problem on a *probed* resource is evidence:
it becomes an HttpExchange and feeds findings. Only problems with the
operator's own request raise ToolFailure: an unusable entry URL, a missing
fixture in demo mode, or an invalid option.
"""

import httpx

from hls_doctor.adapters.http.redact_url import redact_url
from media_ops_contracts.tool_failure import FailureKind, ToolFailure


def require_usable_entry_url(url: str) -> str:
    """Validate the operator-supplied entry URL; returns it unchanged."""
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL as error:
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            f"The URL could not be parsed: {error}.",
            "Check the manifest URL and try again.",
        ) from error
    if parsed.scheme not in ("http", "https"):
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            f"Unsupported URL scheme {parsed.scheme!r}.",
            "Use an http or https manifest URL, or a local file with --base-url.",
        )
    return url


def entry_point_unreachable(url: str, error: Exception) -> ToolFailure:
    """The entry manifest itself could not be fetched at the transport level."""
    return ToolFailure(
        FailureKind.EXTERNAL_SERVICE_UNAVAILABLE,
        f"The entry manifest could not be fetched: {type(error).__name__}.",
        f"Check connectivity and that {redact_url(url)} is reachable, then retry.",
    )


def missing_fixture_exchange(url: str, scenario: str) -> ToolFailure:
    """Demo mode fails closed when a URL has no recorded exchange."""
    return ToolFailure(
        FailureKind.INVALID_REQUEST,
        f"No recorded exchange for {redact_url(url)} in scenario {scenario}.",
        "Record it with scripts/record_hls_fixtures.py or pick another DEMO_SCENARIO.",
    )
