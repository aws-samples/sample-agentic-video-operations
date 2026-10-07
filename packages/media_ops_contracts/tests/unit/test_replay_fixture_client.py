import json

import pytest

from media_ops_contracts.create_aws_client import create_aws_client
from media_ops_contracts.replay_fixture_client import ReplayFixtureClient
from media_ops_contracts.tool_failure import FailureKind, ToolFailure


@pytest.fixture
def fixtures_dir(tmp_path):
    scenario = tmp_path / "input_loss"
    scenario.mkdir()
    (scenario / "medialive.list_channels.json").write_text(json.dumps({"Channels": [{"Id": "1"}]}))
    sequence = {"sequence": [{"State": "RUNNING"}, {"State": "STOPPING"}, {"State": "IDLE"}]}
    (scenario / "medialive.describe_channel.json").write_text(json.dumps(sequence))
    return tmp_path


def test_demo_scenario_returns_replay_client_instead_of_boto3(fixtures_dir):
    client = create_aws_client(
        "medialive",
        region="us-west-2",
        demo=True,
        demo_scenario="input_loss",
        fixtures_dir=fixtures_dir,
    )
    assert isinstance(client, ReplayFixtureClient)


def test_answers_operation_from_fixture_and_records_the_call(fixtures_dir):
    client = ReplayFixtureClient("medialive", scenario="input_loss", fixtures_dir=fixtures_dir)
    assert client.list_channels(MaxResults=10) == {"Channels": [{"Id": "1"}]}
    assert client.calls == [("list_channels", {"MaxResults": 10})]


def test_sequence_fixture_returns_states_in_order_then_repeats_the_last(fixtures_dir):
    client = ReplayFixtureClient("medialive", scenario="input_loss", fixtures_dir=fixtures_dir)
    states = [client.describe_channel(ChannelId="1")["State"] for _ in range(4)]
    assert states == ["RUNNING", "STOPPING", "IDLE", "IDLE"]


def test_paginator_yields_the_fixture_as_one_page(fixtures_dir):
    client = ReplayFixtureClient("medialive", scenario="input_loss", fixtures_dir=fixtures_dir)
    pages = list(client.get_paginator("list_channels").paginate())
    assert pages == [{"Channels": [{"Id": "1"}]}]


def test_missing_fixture_fails_loudly_instead_of_returning_empty_data(fixtures_dir):
    client = ReplayFixtureClient("medialive", scenario="input_loss", fixtures_dir=fixtures_dir)
    with pytest.raises(ToolFailure) as failure:
        client.stop_channel(ChannelId="1")
    assert failure.value.kind is FailureKind.INVALID_REQUEST
    assert "medialive.stop_channel" in failure.value.message


@pytest.mark.parametrize("sequence", [[], {"State": "IDLE"}, "IDLE"])
def test_empty_or_non_list_sequence_is_an_invalid_request(fixtures_dir, sequence):
    path = fixtures_dir / "input_loss" / "medialive.describe_input.json"
    path.write_text(json.dumps({"sequence": sequence}))
    client = ReplayFixtureClient("medialive", scenario="input_loss", fixtures_dir=fixtures_dir)
    with pytest.raises(ToolFailure) as failure:
        client.describe_input(InputId="1")
    assert failure.value.kind is FailureKind.INVALID_REQUEST


# A recorded AWS error (extend_agentic_iops_streaming.md §8.3):
# {"error": {"Code": ..., "Message": ...}}, as the whole fixture or one sequence element, raises
# the ClientError AWS would have raised, so adapters classify it exactly as the real one.
def write_fixture(tmp_path, operation, body):
    scenario = tmp_path / "workflow"
    scenario.mkdir(exist_ok=True)
    (scenario / f"medialive.{operation}.json").write_text(json.dumps(body))
    return ReplayFixtureClient("medialive", scenario="workflow", fixtures_dir=tmp_path)


def test_a_recorded_error_in_a_sequence_raises_the_aws_client_error(tmp_path):
    from botocore.exceptions import ClientError

    from media_ops_contracts.classify_aws_error import classify_aws_error

    client = write_fixture(tmp_path, "get_signal_map", {"sequence": [
        {"Id": "sm-1", "Status": "CREATE_COMPLETE"},
        {"error": {"Code": "NotFoundException", "Message": "Signal map not found"}},
    ]})  # fmt: skip

    assert client.get_signal_map(Identifier="sm-1")["Status"] == "CREATE_COMPLETE"
    with pytest.raises(ClientError) as raised:
        client.get_signal_map(Identifier="sm-1")
    assert raised.value.response["Error"] == {
        "Code": "NotFoundException",
        "Message": "Signal map not found",
    }
    assert raised.value.operation_name == "GetSignalMap"
    failure = classify_aws_error(raised.value, operation="Get signal map")
    assert failure.kind is FailureKind.RESOURCE_NOT_FOUND
    assert client.calls == [("get_signal_map", {"Identifier": "sm-1"})] * 2


def test_a_whole_fixture_can_be_a_recorded_error_and_the_last_one_repeats(tmp_path):
    from botocore.exceptions import ClientError

    denied = {"error": {"Code": "AccessDeniedException"}}
    client = write_fixture(tmp_path, "delete_signal_map", denied)
    for _ in range(2):
        with pytest.raises(ClientError) as raised:
            client.delete_signal_map(Identifier="sm-1")
        assert raised.value.response["Error"]["Code"] == "AccessDeniedException"


def test_an_error_entry_without_a_code_is_an_invalid_fixture(tmp_path):
    client = write_fixture(tmp_path, "get_signal_map", {"sequence": [{"error": {"Message": "x"}}]})
    with pytest.raises(ToolFailure) as failure:
        client.get_signal_map(Identifier="sm-1")
    assert failure.value.kind is FailureKind.INVALID_REQUEST
