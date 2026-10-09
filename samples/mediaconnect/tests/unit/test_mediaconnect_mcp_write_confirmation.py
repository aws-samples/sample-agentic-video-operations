"""A stdio MCP flow write runs only after the human types the exact flow ARN.

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

from mediaconnect_mcp.bootstrap.create_mediaconnect_clients import create_mediaconnect_clients
from mediaconnect_mcp.entrypoints.serve_mcp import build_mediaconnect_server
from mediaconnect_mcp.settings.runtime_settings import RuntimeSettings

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures"
FLOW_FIXTURE = json.loads(
    (FIXTURES / "srt_packet_loss" / "mediaconnect.describe_flow.json").read_text()
)
FLOW = FLOW_FIXTURE["sequence"][0]["Flow"]["FlowArn"]
OTHER_FLOW = "arn:aws:mediaconnect:us-west-2:111122223333:flow:other:flow-2"


class FakeMediaConnect:
    """describe_flow follows the writes; every write is recorded."""

    def __init__(self, status: str) -> None:
        self.status = status
        self.writes: list[tuple[str, str]] = []

    def describe_flow(self, FlowArn: str) -> dict:  # noqa: N803 (boto3's parameter name)
        response = copy.deepcopy(FLOW_FIXTURE["sequence"][0])
        response["Flow"]["Status"] = self.status
        return response

    def stop_flow(self, FlowArn: str) -> dict:  # noqa: N803
        self.writes.append(("stop_flow", FlowArn))
        self.status = "STANDBY"
        return {"FlowArn": FlowArn, "Status": "STOPPING"}

    def start_flow(self, FlowArn: str) -> dict:  # noqa: N803
        self.writes.append(("start_flow", FlowArn))
        self.status = "ACTIVE"
        return {"FlowArn": FlowArn, "Status": "STARTING"}


def operator_types(text: str):
    """An operator who reads the request and types `text`."""

    async def handler(message, response_type, params, context):
        handler.asked.append(message)
        return text

    handler.asked = []
    return handler


async def operator_declines(message, response_type, params, context):
    return ElicitResult(action="decline")


async def operator_cancels(message, response_type, params, context):
    return ElicitResult(action="cancel")


@pytest.fixture
def server_and_flow():
    settings = RuntimeSettings(
        aws_region="us-west-2",
        allow_writes=True,
        demo=True,
        demo_scenario="srt_packet_loss",
        fixtures_dir=FIXTURES,
    )
    media_connect = FakeMediaConnect("ACTIVE")
    clients = replace(create_mediaconnect_clients(settings), mediaconnect=media_connect)
    return build_mediaconnect_server(settings, clients), media_connect


def call(server, tool, arguments, elicitation_handler=None):
    async def run():
        async with Client(server, elicitation_handler=elicitation_handler) as client:
            return await client.call_tool(tool, arguments, raise_on_error=False)

    return asyncio.run(run())


def test_the_write_tools_take_no_confirmation_from_the_model(server_and_flow):
    server, _ = server_and_flow
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}

    for name in ("start_flow", "stop_flow"):
        assert set(tools[name].parameters["properties"]) == {"flow_arn"}, name


def test_a_client_that_cannot_ask_the_operator_cannot_write(server_and_flow):
    server, media_connect = server_and_flow

    result = call(server, "stop_flow", {"flow_arn": FLOW})

    assert result.is_error
    text = result.content[0].text
    assert "ApprovalRequired" in text and "elicitation" in text
    assert media_connect.writes == []


def test_the_operator_typing_the_exact_arn_runs_the_write(server_and_flow):
    server, media_connect = server_and_flow
    operator = operator_types(FLOW)

    result = call(server, "stop_flow", {"flow_arn": FLOW}, operator)

    assert not result.is_error, result.content[0].text
    assert media_connect.writes == [("stop_flow", FLOW)]
    [asked] = operator.asked
    assert "stop_flow" in asked and FLOW in asked
    assert json.loads(result.content[0].text)["verified"] is True


@pytest.mark.parametrize("typed", [OTHER_FLOW, FLOW.upper(), f" {FLOW}", ""])
def test_anything_but_the_exact_arn_is_refused(server_and_flow, typed):
    server, media_connect = server_and_flow

    result = call(server, "stop_flow", {"flow_arn": FLOW}, operator_types(typed))

    assert result.is_error
    assert "ApprovalRequired" in result.content[0].text
    assert media_connect.writes == []


@pytest.mark.parametrize("operator", [operator_declines, operator_cancels])
def test_declining_or_cancelling_changes_nothing(server_and_flow, operator):
    server, media_connect = server_and_flow

    result = call(server, "start_flow", {"flow_arn": FLOW}, operator)

    assert result.is_error
    assert "ApprovalRequired" in result.content[0].text
    assert media_connect.writes == []


# --- Review fix-ups: a client that can't really ask, and concurrent questions ----------

LEAKED = "client transport leaked detail"


async def operator_client_raises(message, response_type, params, context):
    raise RuntimeError(LEAKED)


async def operator_client_answers_garbage(message, response_type, params, context):
    return ElicitResult(action="accept", content={"unexpected": LEAKED})


@pytest.mark.parametrize("operator", [operator_client_raises, operator_client_answers_garbage])
def test_a_broken_eliciting_client_is_a_clean_refusal_with_no_detail(
    server_and_flow, operator, caplog
):
    server, media_connect = server_and_flow
    caplog.set_level(logging.DEBUG)

    result = call(server, "stop_flow", {"flow_arn": FLOW}, operator)

    assert result.is_error
    text = result.content[0].text
    assert "ApprovalRequired" in text and "couldn't ask" in text
    assert LEAKED not in text and LEAKED not in caplog.text
    assert media_connect.writes == []


@pytest.mark.parametrize(
    ("declared", "form"),
    [
        ({}, True),  # the spec's backward-compatible form: no mode named means form
        ({"form": {}}, True),
        ({"form": {}, "url": {}}, True),
        ({"url": {}}, False),  # URL-only: it can't show our question
        (None, False),
    ],
)
def test_only_a_client_that_supports_form_elicitation_is_asked(declared, form):
    from mcp.types import ClientCapabilities

    from mediaconnect_mcp.entrypoints.confirm_with_operator import supports_form_elicitation

    capabilities = ClientCapabilities.model_validate(
        {} if declared is None else {"elicitation": declared}
    )
    assert supports_form_elicitation(capabilities) is form


class TwoFlows:
    """Two flows, each with its own state; every write is recorded."""

    def __init__(self) -> None:
        self.status = {FLOW: "ACTIVE", OTHER_FLOW: "ACTIVE"}
        self.writes: list[tuple[str, str]] = []

    def describe_flow(self, FlowArn: str) -> dict:  # noqa: N803
        response = copy.deepcopy(FLOW_FIXTURE["sequence"][0])
        response["Flow"]["FlowArn"], response["Flow"]["Status"] = FlowArn, self.status[FlowArn]
        return response

    def stop_flow(self, FlowArn: str) -> dict:  # noqa: N803
        self.writes.append(("stop_flow", FlowArn))
        self.status[FlowArn] = "STANDBY"
        return {"FlowArn": FlowArn, "Status": "STOPPING"}


def test_concurrent_writes_each_get_their_own_operator_answer():
    settings = RuntimeSettings(
        aws_region="us-west-2", allow_writes=True, demo=True,
        demo_scenario="srt_packet_loss", fixtures_dir=FIXTURES,
    )  # fmt: skip
    flows = TwoFlows()
    server = build_mediaconnect_server(
        settings, replace(create_mediaconnect_clients(settings), mediaconnect=flows)
    )

    async def operator(message, response_type, params, context):
        # Reads the question it was shown; the first one waits, so the answers cross over.
        arn = FLOW if FLOW in message else OTHER_FLOW
        if arn == FLOW:
            await asyncio.sleep(0.2)
        return arn

    async def both():
        async with Client(server, elicitation_handler=operator) as client:
            return await asyncio.gather(
                client.call_tool("stop_flow", {"flow_arn": FLOW}, raise_on_error=False),
                client.call_tool("stop_flow", {"flow_arn": OTHER_FLOW}, raise_on_error=False),
            )

    first, second = asyncio.run(both())

    assert not first.is_error and not second.is_error
    assert json.loads(first.content[0].text)["resource_id"] == FLOW
    assert json.loads(second.content[0].text)["resource_id"] == OTHER_FLOW
    assert sorted(flows.writes) == sorted([("stop_flow", FLOW), ("stop_flow", OTHER_FLOW)])


def test_an_auto_answering_client_defeats_the_confirmation_as_the_docs_say(server_and_flow):
    """The documented residual: the server sees only the answer, never who typed it."""
    server, media_connect = server_and_flow

    async def answers_by_itself(message, response_type, params, context):
        return next(w.rstrip("?") for w in message.split() if w.startswith("arn:aws:"))

    result = call(server, "stop_flow", {"flow_arn": FLOW}, answers_by_itself)

    assert not result.is_error
    assert media_connect.writes == [("stop_flow", FLOW)]
