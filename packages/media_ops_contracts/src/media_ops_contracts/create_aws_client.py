"""The one way samples create AWS clients (write_safe_tools.md §2, §4)."""

from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config

from media_ops_contracts.replay_fixture_client import ReplayFixtureClient
from media_ops_contracts.tool_failure import FailureKind, ToolFailure

# Explicit timeouts and bounded retries for every AWS call (guidelines §10).
AWS_CLIENT_CONFIG = Config(
    connect_timeout=5,
    read_timeout=30,
    retries={"max_attempts": 3, "mode": "standard"},
)


def create_aws_client(
    service: str,
    *,
    region: str,
    demo: bool,
    demo_scenario: str = "",
    fixtures_dir: Path = Path("fixtures"),
) -> Any:
    """A regional boto3 client, or with `demo=True` a fixture replay client.

    Demo mode fails closed: it never builds a boto3 client. An empty or unknown scenario
    raises ToolFailure instead of silently falling back to real AWS.
    """
    if demo:
        return create_replay_client(service, demo_scenario, fixtures_dir)
    return boto3.client(service, region_name=region, config=AWS_CLIENT_CONFIG)


def create_replay_client(service: str, scenario: str, fixtures_dir: Path) -> ReplayFixtureClient:
    if not scenario:
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            "DEMO is on but no fixture scenario is selected.",
            "Leave DEMO_SCENARIO empty to use the sample's default, or name a folder in fixtures/.",
        )
    if not (fixtures_dir / scenario).is_dir():
        known = sorted(path.name for path in fixtures_dir.glob("*") if path.is_dir())
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            f"Unknown fixture scenario '{scenario}' in {fixtures_dir}.",
            f"Use one of: {', '.join(known) or 'none found'}.",
        )
    return ReplayFixtureClient(service, scenario=scenario, fixtures_dir=fixtures_dir)
