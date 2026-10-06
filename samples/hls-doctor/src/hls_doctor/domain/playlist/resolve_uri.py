"""Resolve playlist URIs against a base, with EXT-X-DEFINE variable substitution."""

import re
from urllib.parse import parse_qs, urljoin, urlsplit

from hls_doctor.domain.playlist.multivariant_model import DefineTag

VARIABLE_PATTERN = re.compile(r"\{\$([a-zA-Z0-9_-]+)\}")


def build_variable_table(
    defines: list[DefineTag], base_url: str, imported: dict[str, str] | None = None
) -> dict[str, str]:
    """NAME/VALUE, IMPORT (from the multivariant table) and QUERYPARAM variables."""
    query = parse_qs(urlsplit(base_url).query)
    table: dict[str, str] = {}
    for define in defines:
        if define.name is not None:
            table[define.name] = define.value or ""
        elif define.import_name is not None:
            table[define.import_name] = (imported or {}).get(define.import_name, "")
        elif define.queryparam is not None:
            values = query.get(define.queryparam, [])
            table[define.queryparam] = values[0] if values else ""
    return table


def substitute_variables(uri: str, variables: dict[str, str]) -> str:
    """Replace {$name} references; unknown names stay verbatim for validators."""
    return VARIABLE_PATTERN.sub(lambda match: variables.get(match.group(1), match.group(0)), uri)


def resolve_uri(uri: str, base_url: str, variables: dict[str, str] | None = None) -> str:
    """Substitute variables, then resolve relative references per RFC 3986."""
    substituted = substitute_variables(uri, variables or {})
    return urljoin(base_url, substituted)
