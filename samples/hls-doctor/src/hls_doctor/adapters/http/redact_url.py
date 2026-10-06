"""Strip credential-shaped query values from URLs before they reach any report."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SENSITIVE_PARAMETER_MARKERS = ("token", "signature", "sig", "key", "auth", "policy", "expires")


def redact_url(url: str, *, redact_all_query: bool = False) -> str:
    """Mask sensitive query values; `redact_all_query` masks every value."""
    parts = urlsplit(url)
    if not parts.query:
        return url
    redacted = [
        (name, "REDACTED" if redact_all_query or is_sensitive(name) else value)
        for name, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit(parts._replace(query=urlencode(redacted)))


def is_sensitive(name: str) -> bool:
    lowered = name.lower()
    return any(marker in lowered for marker in SENSITIVE_PARAMETER_MARKERS)
