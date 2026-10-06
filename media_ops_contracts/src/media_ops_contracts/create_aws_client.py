"""The one way samples create AWS clients (tool-contract §2, §4)."""

from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config

from media_ops_contracts.replay_fixture_client import ReplayFixtureClient

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
    demo_scenario: str | None = None,
    fixtures_dir: Path = Path("fixtures"),
) -> Any:
    """Return a regional boto3 client, or a fixture replay client when `demo_scenario` is set."""
    if demo_scenario:
        return ReplayFixtureClient(service, scenario=demo_scenario, fixtures_dir=fixtures_dir)
    return boto3.client(service, region_name=region, config=AWS_CLIENT_CONFIG)
