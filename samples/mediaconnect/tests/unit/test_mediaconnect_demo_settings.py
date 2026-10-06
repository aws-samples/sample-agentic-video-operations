"""DEMO=1 with the root .env's empty DEMO_SCENARIO never reaches real AWS (backlog T4)."""

import asyncio
from pathlib import Path

import pytest
from fastmcp import Client

from media_ops_contracts import create_aws_client
from mediaconnect_mcp.entrypoints.serve_mcp import build_mediaconnect_server
from mediaconnect_mcp.settings.runtime_settings import DEFAULT_DEMO_SCENARIO, RuntimeSettings

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures"


@pytest.fixture
def demo_with_empty_scenario(monkeypatch):
    monkeypatch.setenv("DEMO", "1")
    monkeypatch.setenv("DEMO_SCENARIO", "")
    monkeypatch.setenv("FIXTURES_DIR", str(FIXTURES))

    def refuse(*args, **kwargs):
        raise AssertionError("demo mode built a real boto3 client")

    monkeypatch.setattr(create_aws_client.boto3, "client", refuse)


def test_an_empty_demo_scenario_means_the_mediaconnect_default(demo_with_empty_scenario):
    assert RuntimeSettings().demo_scenario == DEFAULT_DEMO_SCENARIO == "srt_packet_loss"


def test_the_demo_server_answers_from_fixtures_without_boto3(demo_with_empty_scenario):
    async def call():
        async with Client(build_mediaconnect_server()) as client:
            return await client.call_tool("list_flows")

    assert asyncio.run(call()).structured_content["flows"]
