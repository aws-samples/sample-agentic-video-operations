"""Bound and neutralize remote text before it enters finding prose.

Playlist bodies, asset lists and header values are untrusted data. Anything
quoted into a finding - and therefore shown to an operator or fed to a model -
is length-bounded and stripped of control characters so remote content cannot
format, truncate or impersonate parts of a report.
"""

MAX_QUOTED_CHARS = 120


def quote_untrusted(text: str, limit: int = MAX_QUOTED_CHARS) -> str:
    cleaned = "".join(character if character.isprintable() else " " for character in text)
    if len(cleaned) > limit:
        return cleaned[:limit] + "…"
    return cleaned
