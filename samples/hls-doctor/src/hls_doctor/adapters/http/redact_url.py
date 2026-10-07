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


QUOTED_QUERY_PATTERN = re.compile(r'"([^"]*\?[^"]*)"')
DEFINE_VALUE_PATTERN = re.compile(r'(VALUE=")[^"]*(")')


def redact_playlist_body(text: str) -> str:
    """Redact credentials inside a playlist body before it is stored or returned.

    Every `?...` query anywhere in the text is redacted (quoted attribute
    values and bare URI lines alike), keeping only the structural `_HLS_*`
    parameters, and EXT-X-DEFINE values are treated as secrets outright:
    variables exist precisely to carry tokens into URIs.
    """
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#EXT-X-DEFINE"):
            lines.append(DEFINE_VALUE_PATTERN.sub(r"\1REDACTED\2", line))
        elif stripped and not stripped.startswith("#"):
            lines.append(redact_url(stripped) if "?" in stripped else line)
        elif "?" in line:
            lines.append(
                QUOTED_QUERY_PATTERN.sub(lambda match: f'"{redact_url(match.group(1))}"', line)
            )
        else:
            lines.append(line)
    return "\n".join(lines)
