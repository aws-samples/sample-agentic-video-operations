from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from media_ops_contracts.call_aws_operation import call_aws_operation
from media_ops_contracts.tool_failure import FailureKind, ToolFailure


def test_returns_the_operation_response_and_passes_parameters():
    client = Mock()
    client.describe_channel.return_value = {"State": "IDLE"}
    assert call_aws_operation(client, "describe_channel", ChannelId="1") == {"State": "IDLE"}
    client.describe_channel.assert_called_once_with(ChannelId="1")


def test_sdk_errors_become_classified_failures_with_the_cause_kept():
    client = Mock()
    error = ClientError({"Error": {"Code": "NotFoundException"}}, "DescribeChannel")
    client.describe_channel.side_effect = error
    with pytest.raises(ToolFailure) as failure:
        call_aws_operation(client, "describe_channel", ChannelId="1")
    assert failure.value.kind is FailureKind.RESOURCE_NOT_FOUND
    assert failure.value.__cause__ is error


def test_tool_failures_from_replay_clients_pass_through_unchanged():
    client = Mock()
    original = ToolFailure(FailureKind.INVALID_REQUEST, "No fixture", "Add it")
    client.describe_channel.side_effect = original
    with pytest.raises(ToolFailure) as failure:
        call_aws_operation(client, "describe_channel", ChannelId="1")
    assert failure.value is original


def test_collect_pages_follows_next_token_until_the_last_page():
    client = Mock()
    client.list_channels.side_effect = [
        {"Channels": [{"Id": "1"}], "NextToken": "t1"},
        {"Channels": [{"Id": "2"}]},
    ]
    from media_ops_contracts.call_aws_operation import collect_pages

    assert collect_pages(client, "list_channels", "Channels", MaxResults=1) == [
        {"Id": "1"},
        {"Id": "2"},
    ]
    assert client.list_channels.call_args_list[1].kwargs == {"MaxResults": 1, "NextToken": "t1"}
