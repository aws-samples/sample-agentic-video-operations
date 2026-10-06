"""RFC 8216 §4.2 attribute-list parsing: NAME=value pairs with quoted strings."""


def parse_attribute_list(value: str) -> dict[str, str]:
    """Attribute names to raw values; quoted strings lose their quotes only.

    Order is preserved (dict insertion order). Malformed trailing text is kept
    under the pseudo-name `_TRAILING` so validators can flag it as evidence.
    """
    attributes: dict[str, str] = {}
    position = 0
    while position < len(value):
        equals = value.find("=", position)
        if equals == -1:
            trailing = value[position:].strip(", ")
            if trailing:
                attributes["_TRAILING"] = trailing
            break
        name = value[position:equals].strip().lstrip(",").strip()
        position = equals + 1
        if position < len(value) and value[position] == '"':
            closing = value.find('"', position + 1)
            if closing == -1:
                attributes[name] = value[position + 1 :]
                break
            attributes[name] = value[position + 1 : closing]
            position = closing + 1
            comma = value.find(",", position)
            position = len(value) if comma == -1 else comma + 1
        else:
            comma = value.find(",", position)
            end = len(value) if comma == -1 else comma
            attributes[name] = value[position:end].strip()
            position = end + 1
    return attributes


def parse_decimal(raw: str | None) -> float | None:
    """A decimal-floating-point attribute value, or None when absent or malformed."""
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def parse_integer(raw: str | None) -> int | None:
    """A decimal-integer attribute value, or None when absent or malformed."""
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def parse_resolution(raw: str | None) -> tuple[int, int] | None:
    """A WIDTHxHEIGHT value, or None when absent or malformed."""
    if raw is None or "x" not in raw:
        return None
    width_text, _, height_text = raw.partition("x")
    try:
        return int(width_text), int(height_text)
    except ValueError:
        return None
