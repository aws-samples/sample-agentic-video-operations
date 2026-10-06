"""Create an InfluxDB-shaped query callable backed by one root fixture."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from media_ops_contracts.load_fixture import load_fixture
from media_ops_contracts.tool_failure import FailureKind, ToolFailure


def replay_influxdb_query(
    fixtures_dir: Path,
    scenario: str,
    fixture_name: str,
) -> Callable[[str], list[dict[str, Any]]]:
    """Return recorded query responses, consuming a sequence when present."""
    recorded = load_fixture(fixtures_dir, scenario, fixture_name)
    responses = recorded.get("sequence") if isinstance(recorded, dict) else [recorded]
    if not isinstance(responses, list) or not responses:
        _reject_fixture(fixture_name)
    if any(
        not isinstance(response, list) or any(not isinstance(record, dict) for record in response)
        for response in responses
    ):
        _reject_fixture(fixture_name)

    position = 0

    def query_influxdb(_: str) -> list[dict[str, Any]]:
        nonlocal position
        response = responses[min(position, len(responses) - 1)]
        position += 1
        return response

    return query_influxdb


def _reject_fixture(fixture_name: str) -> None:
    raise ToolFailure(
        FailureKind.INVALID_REQUEST,
        f"Fixture {fixture_name} must contain records or a non-empty sequence of records.",
        "Fix the recorded fixture.",
    )
