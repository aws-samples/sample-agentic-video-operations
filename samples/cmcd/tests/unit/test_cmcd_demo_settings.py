"""DEMO=1 with the root .env's empty DEMO_SCENARIO replays cmcd's own scenario."""

import asyncio
from pathlib import Path

from fastmcp import Client

from cmcd_mcp.entrypoints.serve_mcp import build_cmcd_server
from cmcd_mcp.settings.runtime_settings import DEFAULT_DEMO_SCENARIO, RuntimeSettings

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures"


def test_an_empty_demo_scenario_means_the_cmcd_default(monkeypatch):
    monkeypatch.setenv("DEMO", "1")
    monkeypatch.setenv("DEMO_SCENARIO", "")
    assert RuntimeSettings().demo_scenario == DEFAULT_DEMO_SCENARIO == "cmcd_rebuffering"


def test_the_demo_server_starts_and_answers_with_an_empty_demo_scenario(monkeypatch):
    monkeypatch.setenv("DEMO", "1")
    monkeypatch.setenv("DEMO_SCENARIO", "")
    monkeypatch.setenv("FIXTURES_DIR", str(FIXTURES))

    async def call():
        async with Client(build_cmcd_server()) as client:
            return await client.call_tool("analyze_buffer_events")

    assert asyncio.run(call()).structured_content["low_buffer_count"] == 3
