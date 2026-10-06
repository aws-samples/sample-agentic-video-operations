"""DEMO=1 with the root .env's empty DEMO_SCENARIO never reaches real AWS (backlog T4)."""

from pathlib import Path

import pytest

from media_ops_contracts import create_aws_client
from media_ops_contracts.replay_fixture_client import ReplayFixtureClient
from medialive_mcp.bootstrap.create_medialive_clients import create_medialive_clients
from medialive_mcp.settings.runtime_settings import DEFAULT_DEMO_SCENARIO, RuntimeSettings

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures"


@pytest.fixture
def demo_with_empty_scenario(monkeypatch):
    monkeypatch.setenv("DEMO", "1")
    monkeypatch.setenv("DEMO_SCENARIO", "")
    monkeypatch.setenv("FIXTURES_DIR", str(FIXTURES))

    def refuse(*args, **kwargs):
        raise AssertionError("demo mode built a real boto3 client")

    monkeypatch.setattr(create_aws_client.boto3, "client", refuse)


def test_an_empty_demo_scenario_means_the_medialive_default(demo_with_empty_scenario):
    assert RuntimeSettings().demo_scenario == DEFAULT_DEMO_SCENARIO == "input_loss"


def test_every_demo_client_is_a_replay_client(demo_with_empty_scenario):
    clients = create_medialive_clients(RuntimeSettings())
    assert all(
        isinstance(client, ReplayFixtureClient)
        for client in (clients.medialive, clients.cloudwatch, clients.logs, clients.bedrock)
    )
