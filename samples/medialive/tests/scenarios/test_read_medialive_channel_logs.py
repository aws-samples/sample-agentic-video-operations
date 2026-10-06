from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

from botocore.exceptions import ClientError

from medialive_mcp.adapters.cloudwatch_logs.read_channel_logs import (
    LOG_GROUP,
    MAX_EVENTS,
    MAX_LOG_PAGES,
    ChannelLogStatus,
    read_channel_logs,
)

CHANNEL = "1234567"
REGION = "us-west-2"
ACCOUNT = "111122223333"
WINDOW_END = datetime(2026, 10, 6, 12, tzinfo=UTC)
WINDOW = (WINDOW_END - timedelta(hours=1), WINDOW_END)
PREFIX = f"arn_aws_medialive_{REGION}_{ACCOUNT}_channel_{CHANNEL}_"


def clients(*, log_level="INFO", streams=None, pages=None):
    medialive = Mock()
    medialive.describe_channel.return_value = {"Id": CHANNEL, "LogLevel": log_level}
    sts = Mock()
    sts.get_caller_identity.return_value = {"Account": ACCOUNT}
    logs = Mock()
    logs.describe_log_streams.return_value = {
        "logStreams": [{"logStreamName": f"{PREFIX}0"}] if streams is None else streams
    }
    logs.filter_log_events.side_effect = pages or [{"events": []}]
    return SimpleNamespace(medialive=medialive, logs=logs, sts=sts)


def event(number):
    return {
        "timestamp": number,
        "logStreamName": f"{PREFIX}0",
        "message": f"event {number}",
    }


def test_read_channel_logs_targets_the_elemental_group_and_channel_streams():
    services = clients(pages=[{"events": [event(1)]}])

    result = read_channel_logs(services, CHANNEL, WINDOW, REGION)

    assert result.status is ChannelLogStatus.AVAILABLE
    assert result.events[0].message == "event 1"
    services.logs.describe_log_streams.assert_called_once_with(
        logGroupName=LOG_GROUP,
        logStreamNamePrefix=PREFIX,
        limit=1,
    )
    assert services.logs.filter_log_events.call_args.kwargs["logGroupName"] == LOG_GROUP
    assert services.logs.filter_log_events.call_args.kwargs["logStreamNamePrefix"] == PREFIX


def test_read_channel_logs_paginates_before_returning_the_newest_events():
    first_page = {"events": [event(number) for number in range(1, 31)], "nextToken": "next"}
    second_page = {"events": [event(number) for number in range(31, 56)]}
    services = clients(pages=[first_page, second_page])

    result = read_channel_logs(services, CHANNEL, WINDOW, REGION)

    assert len(result.events) == MAX_EVENTS
    assert [item.message for item in result.events] == [
        f"event {number}" for number in range(36, 56)
    ]
    assert services.logs.filter_log_events.call_count == 2
    assert services.logs.filter_log_events.call_args_list[1].kwargs["nextToken"] == "next"


def test_read_channel_logs_caps_pages_and_returned_events():
    pages = [
        {
            "events": [event(page * MAX_EVENTS + number) for number in range(MAX_EVENTS)],
            "nextToken": f"next-{page}",
        }
        for page in range(MAX_LOG_PAGES + 1)
    ]
    services = clients(pages=pages)

    result = read_channel_logs(services, CHANNEL, WINDOW, REGION)

    assert services.logs.filter_log_events.call_count == MAX_LOG_PAGES
    assert len(result.events) == MAX_EVENTS
    calls = services.logs.filter_log_events.call_args_list
    assert all(call.kwargs["limit"] == MAX_EVENTS for call in calls)
    assert all(call.kwargs["startFromHead"] is False for call in calls)


def test_read_channel_logs_excludes_as_run_schedule_events():
    as_run = {
        "timestamp": 2,
        "logStreamName": f"{PREFIX}0_as_run",
        "message": "input switch executed",
    }
    services = clients(pages=[{"events": [event(1), as_run, event(3)]}])

    result = read_channel_logs(services, CHANNEL, WINDOW, REGION)

    assert [item.message for item in result.events] == ["event 1", "event 3"]


def test_read_channel_logs_returns_typed_empty_result_when_logging_is_disabled():
    services = clients(log_level="DISABLED")

    result = read_channel_logs(services, CHANNEL, WINDOW, REGION)

    assert result.status is ChannelLogStatus.LOGGING_DISABLED
    assert result.events == []
    assert "disabled" in result.reason.lower()
    services.sts.get_caller_identity.assert_not_called()
    services.logs.describe_log_streams.assert_not_called()


def test_read_channel_logs_returns_typed_empty_result_when_no_streams_exist():
    services = clients(streams=[])

    result = read_channel_logs(services, CHANNEL, WINDOW, REGION)

    assert result.status is ChannelLogStatus.LOGGING_DISABLED
    assert result.events == []
    assert "no medialive log streams" in result.reason.lower()
    services.logs.filter_log_events.assert_not_called()


def test_read_channel_logs_treats_a_missing_log_group_as_disabled():
    services = clients()
    services.logs.describe_log_streams.side_effect = ClientError(
        {"Error": {"Code": "ResourceNotFoundException", "Message": "not found"}},
        "DescribeLogStreams",
    )

    result = read_channel_logs(services, CHANNEL, WINDOW, REGION)

    assert result.status is ChannelLogStatus.LOGGING_DISABLED
    assert result.events == []
    assert "no medialive log group" in result.reason.lower()
    services.logs.filter_log_events.assert_not_called()
