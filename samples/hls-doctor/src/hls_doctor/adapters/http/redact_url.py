"""Unconditional URL redaction: no query value survives into any report.

Tokenized stream URLs carry credentials under arbitrary parameter names
(hdnts, wmsAuthSign, token, ...), so guessing names is not a defense: every
value is replaced except the LL-HLS delivery directives, whose values are
structural sequence numbers the diagnosis needs.
"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

STRUCTURAL_QUERY_PARAMETERS = frozenset({"_HLS_msn", "_HLS_part", "_HLS_skip"})


def redact_url(url: str) -> str:
    """Replace every query value with REDACTED except the LL-HLS directives."""
    parts = urlsplit(url)
    if not parts.query:
        return url
    redacted = [
        (name, value if name in STRUCTURAL_QUERY_PARAMETERS else "REDACTED")
        for name, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit(parts._replace(query=urlencode(redacted)))
