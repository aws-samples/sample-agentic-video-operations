"""Quote one untrusted string for interpolation into a Flux query."""

import json


def quote_flux_string(value: str) -> str:
    """Return a Flux string literal with variable interpolation disabled."""
    return json.dumps(value).replace("$", r"\$")
