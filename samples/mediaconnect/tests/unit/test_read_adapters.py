import json
from datetime import UTC, datetime

import pytest
from botocore.exceptions import ClientError

from media_ops_contracts.replay_fixture_client import ReplayFixtureClient
from media_ops_contracts.tool_failure import FailureKind, ToolFailure
from mediaconnect_mcp.adapters.bedrock.describe_thumbnail import (
    ThumbnailDescription,
    describe_thumbnail,
)
from mediaconnect_mcp.adapters.cloudwatch.read_flow_metrics import (
    FlowMetrics,
    MetricCategory,
    read_flow_metrics,
)
from mediaconnect_mcp.adapters.media_connect.describe_flow import (
    FlowDetails,
    FlowState,
    describe_flow,
)
from mediaconnect_mcp.adapters.media_connect.describe_flow_source_metadata import (
    FlowSourceMetadata,
    describe_flow_source_metadata,
)
from mediaconnect_mcp.adapters.media_connect.list_flows import FlowList, list_flows
from mediaconnect_mcp.adapters.media_connect.read_flow_thumbnail import (
    FlowThumbnail,
    read_flow_thumbnail,
)

FLOW_ARN = "arn:aws:mediaconnect:us-west-2:111122223333:flow:demo-flow:flow-1"
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def record_fixture(fixtures_dir, service, operation, response):
    scenario = fixtures_dir / "adapter_reads"
    scenario.mkdir(exist_ok=True)
    (scenario / f"{service}.{operation}.json").write_text(json.dumps(response))
    return ReplayFixtureClient(service, scenario=scenario.name, fixtures_dir=fixtures_dir)


def test_list_flows_returns_typed_fixture_records(tmp_path):
    client = record_fixture(
        tmp_path,
        "mediaconnect",
        "list_flows",
        {
            "Flows": [
                {
                    "FlowArn": FLOW_ARN,
                    "Name": "demo-flow",
                    "Status": "ACTIVE",
                    "SourceType": "OWNED",
                }
            ]
        },
    )

    result = list_flows(client)

    assert isinstance(result, FlowList)
    assert result.count == 1
    assert result.flows[0].state is FlowState.ACTIVE


def test_describe_flow_returns_typed_topology(tmp_path):
    client = record_fixture(
        tmp_path,
        "mediaconnect",
        "describe_flow",
        {
            "Flow": {
                "FlowArn": FLOW_ARN,
                "Name": "demo-flow",
                "Status": "ACTIVE",
                "Source": {"Name": "primary-source"},
                "Outputs": [{"Name": "distribution-output"}],
            },
            "Messages": {"Errors": []},
        },
    )

    result = describe_flow(client, FLOW_ARN)

    assert isinstance(result, FlowDetails)
    assert result.state is FlowState.ACTIVE
    assert result.source["Name"] == "primary-source"


def test_describe_flow_classifies_client_errors_without_raw_details():
    class AccessDeniedClient:
        def describe_flow(self, **_kwargs):
            raise ClientError(
                {
                    "Error": {
                        "Code": "AccessDeniedException",
                        "Message": "raw internal detail",
                    },
                    "ResponseMetadata": {"RequestId": "internal-request-id"},
                },
                "DescribeFlow",
            )

    with pytest.raises(ToolFailure) as failure:
        describe_flow(AccessDeniedClient(), FLOW_ARN)

    assert failure.value.kind is FailureKind.PERMISSION_DENIED
    assert "raw internal detail" not in failure.value.message
    assert "internal-request-id" not in failure.value.message
    assert failure.value.next_action


def test_describe_flow_source_metadata_returns_typed_transport_details(tmp_path):
    client = record_fixture(
        tmp_path,
        "mediaconnect",
        "describe_flow_source_metadata",
        {
            "FlowArn": FLOW_ARN,
            "Timestamp": NOW.isoformat(),
            "TransportMediaInfo": {"Programs": [{"ProgramNumber": 1}]},
            "Messages": [{"Code": "INFO", "Message": "Source connected"}],
        },
    )

    result = describe_flow_source_metadata(client, FLOW_ARN)

    assert isinstance(result, FlowSourceMetadata)
    assert result.observed_at == NOW
    assert result.transport_media_info["Programs"][0]["ProgramNumber"] == 1


def test_read_flow_thumbnail_returns_typed_image_metadata(tmp_path):
    client = record_fixture(
        tmp_path,
        "mediaconnect",
        "describe_flow_source_thumbnail",
        {
            "ThumbnailDetails": {
                "FlowArn": FLOW_ARN,
                "Thumbnail": "ZmFrZS1qcGVn",
                "Timestamp": NOW.isoformat(),
                "Timecode": "12:00:00:00",
                "ThumbnailMessages": [],
            }
        },
    )

    result = read_flow_thumbnail(client, FLOW_ARN)

    assert isinstance(result, FlowThumbnail)
    assert result.image_base64 == "ZmFrZS1qcGVn"
    assert result.observed_at == NOW


def test_read_flow_metrics_returns_typed_fixture_series(tmp_path):
    client = record_fixture(
        tmp_path,
        "cloudwatch",
        "get_metric_data",
        {
            "MetricDataResults": [
                {
                    "Id": "m0_sourcearqrecovered",
                    "Label": "SourceARQRecovered",
                    "StatusCode": "Complete",
                    "Timestamps": [NOW.isoformat()],
                    "Values": [17],
                }
            ]
        },
    )

    result = read_flow_metrics(
        client,
        FLOW_ARN,
        MetricCategory.SOURCE_HEALTH,
        hours_back=1,
        now=NOW,
    )

    assert isinstance(result, FlowMetrics)
    assert result.series[0].name == "SourceARQRecovered"
    assert result.series[0].points[0].value == 17


def test_describe_thumbnail_returns_typed_model_evidence(tmp_path):
    client = record_fixture(
        tmp_path,
        "bedrock-runtime",
        "converse",
        {
            "output": {
                "message": {"content": [{"text": "The live frame shows normal program video."}]}
            }
        },
    )

    result = describe_thumbnail(client, "ZmFrZS1qcGVn", "demo-thumbnail-model")

    assert isinstance(result, ThumbnailDescription)
    assert result.text == "The live frame shows normal program video."
    assert result.model_id == "demo-thumbnail-model"
    operation, request = client.calls[0]
    assert operation == "converse"
    assert request["messages"][0]["content"][1]["image"]["source"]["bytes"] == b"fake-jpeg"
