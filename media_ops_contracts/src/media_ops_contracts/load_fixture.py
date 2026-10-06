"""Read recorded responses from fixtures/<scenario>/ (tool-contract §4)."""

import json
from pathlib import Path
from typing import Any

from media_ops_contracts.tool_failure import FailureKind, ToolFailure


def load_fixture(fixtures_dir: Path, scenario: str, name: str) -> Any:
    """Return the parsed JSON of fixtures/<scenario>/<name>.json, or raise ToolFailure."""
    path = fixtures_dir / scenario / f"{name}.json"
    if not path.is_file():
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            f"No fixture for {name} in scenario {scenario}",
            f"Add {path} or unset DEMO.",
        )
    return json.loads(path.read_text())
