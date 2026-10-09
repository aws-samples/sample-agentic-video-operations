"""A stdio MCP channel write runs only after the human types the exact channel id.

The server asks through MCP elicitation, so the answer comes from the client's user, not
from the model's tool arguments. A client that can't ask refuses every write.
"""

import asyncio
import copy
import json
import logging
from dataclasses import replace
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.client.elicitation import ElicitResult

from medialive_mcp.bootstrap.create_medialive_clients import create_medialive_clients
from medialive_mcp.entrypoints.serve_mcp import build_mcp_server
from medialive_mcp.settings.runtime_settings import RuntimeSettings

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures"
CHANNEL_FIXTURE = json.loads(
    (FIXTURES / "input_loss" / "medialive.describe_channel.json").read_text()
)
CHANNEL = CHANNEL_FIXTURE["Id"]
WRITE_TOOLS = {
    "start_channel",
    "stop_channel",
    "switch_channel_input",
    "create_input_switch_action",
    "create_scte35_action",
    "create_pause_action",
    "create_unpause_action",
    "delete_schedule_action",
}
SCTE35 = {
    "channel_id": CHANNEL,
    "action_name": "ad-break-1",
    "start_time": "2026-10-06T12:00:00Z",
    "splice_event_id": 7,
    "duration": 2700000,
}


class FakeMediaLive:
    """describe_channel follows start and stop; every write is recorded."""

    def __init__(self, state: str) -> None:
        self.state = state
        self.writes: list[tuple[str, dict]] = []

    def describe_channel(self, ChannelId: str) -> dict:  # noqa: N803 (boto3's parameter name)
        return copy.deepcopy(CHANNEL_FIXTURE) | {"State": self.state}

    def stop_channel(self, **parameters) -> dict:
        self.writes.append(("stop_channel", parameters))
        self.state = "IDLE"
        return {}

    def start_channel(self, **parameters) -> dict:
        self.writes.append(("start_channel", parameters))
        self.state = "RUNNING"
        return {}

    def batch_update_schedule(self, **parameters) -> dict:
        self.writes.append(("batch_update_schedule", parameters))
        return {}


def operator_types(text: str):
    """An operator who reads the request and types `text`."""

    async def handler(message, response_type, params, context):
        handler.asked.append(message)
        return text

    handler.asked = []
    return handler


def operator_declines():
    async def handler(message, response_type, params, context):
        handler.asked.append(message)
        return ElicitResult(action="decline")

    handler.asked = []
    return handler


@pytest.fixture
def server_and_channel():
    settings = RuntimeSettings(
        demo=True, demo_scenario="input_loss", fixtures_dir=FIXTURES, allow_writes=True
    )
    medialive = FakeMediaLive("RUNNING")
    clients = replace(create_medialive_clients(settings), medialive=medialive)
    return build_mcp_server(settings, clients), medialive


def call(server, tool, arguments, elicitation_handler=None):
    async def run():
        async with Client(server, elicitation_handler=elicitation_handler) as client:
            return await client.call_tool(tool, arguments, raise_on_error=False)

    return asyncio.run(run())


def test_no_write_tool_takes_a_confirmation_from_the_model(server_and_channel):
    server, _ = server_and_channel
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}

    assert set(tools) >= WRITE_TOOLS
    for name in WRITE_TOOLS:
        assert "confirm_resource_id" not in tools[name].parameters["properties"], name


def test_a_client_that_cannot_ask_the_operator_cannot_write(server_and_channel):
    server, medialive = server_and_channel

    result = call(server, "stop_channel", {"channel_id": CHANNEL})

    assert result.is_error
    text = result.content[0].text
    assert "ApprovalRequired" in text and "elicitation" in text
    assert medialive.writes == []


def test_the_operator_typing_the_exact_channel_id_runs_the_write(server_and_channel):
    server, medialive = server_and_channel
    operator = operator_types(CHANNEL)

    result = call(server, "stop_channel", {"channel_id": CHANNEL}, operator)

    assert not result.is_error, result.content[0].text
    assert medialive.writes == [("stop_channel", {"ChannelId": CHANNEL})]
    [asked] = operator.asked
    assert "stop_channel" in asked and CHANNEL in asked
    assert json.loads(result.content[0].text)["verified"] is True


@pytest.mark.parametrize("typed", ["7654321", f"{CHANNEL} ", "", "yes"])
def test_anything_but_the_exact_channel_id_is_refused(server_and_channel, typed):
    server, medialive = server_and_channel

    result = call(server, "stop_channel", {"channel_id": CHANNEL}, operator_types(typed))

    assert result.is_error
    assert "ApprovalRequired" in result.content[0].text
    assert medialive.writes == []


def test_the_operator_sees_every_parameter_and_a_decline_changes_nothing(server_and_channel):
    server, medialive = server_and_channel
    operator = operator_declines()

    result = call(server, "create_scte35_action", SCTE35, operator)

    assert result.is_error and "did not approve" in result.content[0].text
    assert medialive.writes == []
    [asked] = operator.asked
    for shown in ("create_scte35_action", CHANNEL, "ad-break-1", "2026-10-06T12:00:00Z", "7"):
        assert shown in asked


def test_a_client_whose_elicitation_fails_is_a_clean_refusal_with_no_detail(
    server_and_channel, caplog
):
    server, medialive = server_and_channel
    caplog.set_level(logging.DEBUG)

    async def operator(message, response_type, params, context):
        raise RuntimeError("client transport leaked detail")

    result = call(server, "stop_channel", {"channel_id": CHANNEL}, operator)

    assert result.is_error
    text = result.content[0].text
    assert "ApprovalRequired" in text and "couldn't ask" in text
    assert "leaked detail" not in text and "leaked detail" not in caplog.text
    assert medialive.writes == []
