"""Unconditional URL redaction: no query value survives into any report.

Tokenized stream URLs carry credentials under arbitrary parameter names
(hdnts, wmsAuthSign, token, ...), so guessing names is not a defense: every
value is replaced except the LL-HLS delivery directives, whose values are
structural sequence numbers the diagnosis needs.
"""

import re
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


URI_ATTRIBUTE_PATTERN = re.compile(r'URI="([^"]*)"')


def redact_playlist_body(text: str) -> str:
    """Redact query values inside a playlist body: URI lines and URI="..." attributes.

    The stored evidence copy of a manifest must not carry the very tokens the
    URL fields already redact (key URIs, tokenized segment URIs).
    """
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "?" in stripped:
            lines.append(redact_url(stripped))
        elif stripped.startswith("#") and 'URI="' in line:
            lines.append(
                URI_ATTRIBUTE_PATTERN.sub(lambda match: f'URI="{redact_url(match.group(1))}"', line)
            )
        else:
            lines.append(line)
    return "\n".join(lines)
