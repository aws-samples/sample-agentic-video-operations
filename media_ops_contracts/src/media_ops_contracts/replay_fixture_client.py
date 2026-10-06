"""A boto3-shaped client that answers from fixtures instead of AWS (tool-contract §4)."""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from media_ops_contracts.load_fixture import load_fixture
from media_ops_contracts.tool_failure import FailureKind, ToolFailure


class ReplayFixtureClient:
    """Answers `client.<operation>(**kwargs)` from fixtures/<scenario>/<service>.<operation>.json.

    A fixture is one response, or {"sequence": [r1, r2, ...]} consumed in order with the
    last response repeating, so a describe call can return the state before and after a write.
    Every call is recorded in `calls` so tests can assert what would have reached AWS.
    """

    def __init__(self, service: str, *, scenario: str, fixtures_dir: Path) -> None:
        self.service = service
        self.scenario = scenario
        self.fixtures_dir = fixtures_dir
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._positions: dict[str, int] = {}

    def __getattr__(self, operation: str) -> Callable[..., Any]:
        if operation.startswith("_"):
            raise AttributeError(operation)
        return lambda **kwargs: self._answer(operation, kwargs)

    def get_paginator(self, operation: str) -> "_ReplayPaginator":
        return _ReplayPaginator(self, operation)

    def _answer(self, operation: str, kwargs: dict[str, Any]) -> Any:
        self.calls.append((operation, kwargs))
        recorded = load_fixture(self.fixtures_dir, self.scenario, f"{self.service}.{operation}")
        if not (isinstance(recorded, dict) and "sequence" in recorded):
            return recorded
        sequence = recorded["sequence"]
        if not isinstance(sequence, list) or not sequence:
            raise ToolFailure(
                FailureKind.INVALID_REQUEST,
                f"Fixture {self.service}.{operation} in scenario {self.scenario} has an invalid "
                "sequence",
                'Make "sequence" a non-empty list of recorded responses.',
            )
        position = self._positions.get(operation, 0)
        self._positions[operation] = position + 1
        return sequence[min(position, len(sequence) - 1)]


class _ReplayPaginator:
    def __init__(self, client: ReplayFixtureClient, operation: str) -> None:
        self._client = client
        self._operation = operation

    def paginate(self, **kwargs: Any) -> Iterator[Any]:
        yield self._client._answer(self._operation, kwargs)
