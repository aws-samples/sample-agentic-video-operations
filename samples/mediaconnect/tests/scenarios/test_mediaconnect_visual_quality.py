"""analyze_flow_visual_quality: a frozen source, the honest unknown states, the P3 rules."""

import asyncio
import base64
import dataclasses
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from botocore.exceptions import ClientError
from generate_quality_fixtures import (
    SRT_FLOW_ARN,
    TRANSPORT_FLOW_ARN,
    metric_id,
    srt_packet_loss_thumbnails,
    synthetic_sequences,
    transport_freeze_fixture,
)

from media_ops_contracts.tool_failure import FailureKind, ToolFailure
from media_ops_video_quality.assess_window import Status
from media_ops_video_quality.quality_thresholds import DEFAULT_THRESHOLDS
from mediaconnect_mcp.adapters.cloudwatch.read_flow_metrics import METRICS_BY_CATEGORY
from mediaconnect_mcp.adapters.media_connect.sample_flow_frames import sample_flow_frames
from mediaconnect_mcp.bootstrap.create_mediaconnect_clients import create_mediaconnect_clients
from mediaconnect_mcp.settings.runtime_settings import RuntimeSettings
from mediaconnect_mcp.tool_surface.create_read_tools import create_read_tools

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures"
MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
START = datetime(2026, 10, 6, 14, 32, tzinfo=UTC)


def runtime(**overrides):
    values = {"demo": True, "demo_scenario": "transport_freeze", "fixtures_dir": FIXTURES}
    return RuntimeSettings(**(values | overrides))


def tool(settings=None, **client_overrides):
    settings = settings or runtime(thumbnail_model_id=MODEL)
    clients = create_mediaconnect_clients(settings)
    if client_overrides:
        clients = dataclasses.replace(clients, **client_overrides)
    tools = {f.__name__: f for f in create_read_tools(settings, clients)}
    return tools["analyze_flow_visual_quality"]


class FakeMediaConnect:
    """describe_flow plus a thumbnail per poll; `thumbnails` of None means no image."""

    def __init__(self, *, status="ACTIVE", monitoring=None, thumbnails=(), messages=()):
        self.status, self.thumbnail_calls = status, 0
        self.monitoring = monitoring or {
            "ThumbnailState": "ENABLED",
            "ContentQualityAnalysisState": "ENABLED",
        }
        self.thumbnails, self.messages = list(thumbnails), list(messages)

    def describe_flow(self, FlowArn):  # noqa: N803 - the boto3 parameter name
        flow = {
            "FlowArn": FlowArn,
            "Status": self.status,
            "SourceMonitoringConfig": self.monitoring,
        }
        flow["Source"] = {"Name": "demo-upstream-srt"}
        return {"Flow": flow, "Messages": {"Errors": []}}

    def describe_flow_source_thumbnail(self, FlowArn):  # noqa: N803
        self.thumbnail_calls += 1
        jpeg = self.thumbnails.pop(0) if self.thumbnails else None
        stamp = START + timedelta(seconds=3 * self.thumbnail_calls)
        details = {"FlowArn": FlowArn, "ThumbnailMessages": self.messages, "Timestamp": stamp}
        if jpeg is not None:
            details["Thumbnail"] = base64.b64encode(jpeg).decode()
        return {"ThumbnailDetails": details}


class FakeCloudWatch:
    """Answers each metric category with the given per-metric values (missing = not emitted)."""

    def __init__(self, values):
        self.values = values

    def get_metric_data(self, MetricDataQueries, **_):  # noqa: N803
        results = []
        for query in MetricDataQueries:
            name = query["MetricStat"]["Metric"]["MetricName"]
            if name in self.values:
                results.append(
                    {"Id": query["Id"], "Label": name, "StatusCode": "Complete",
                     "Timestamps": [START], "Values": [self.values[name]]}
                )  # fmt: skip
        return {"MetricDataResults": results}


class TrustedCleanVision:
    def converse(self, **_):
        answer = {
            "compression_artifacts": 5, "banding": 5, "interlacing_ghosting": 5,
            "slate_or_bars": 5, "overall": 5, "confidence": 0.9, "evidence": "clean",
        }  # fmt: skip
        use = {"toolUse": {"toolUseId": "t", "name": "report_picture_quality", "input": answer}}
        return {"output": {"message": {"role": "assistant", "content": [use]}}}


HEALTHY_TRANSPORT = {
    "FrozenFramesBreaching": 0.0,
    "BlackFramesBreaching": 0.0,
    "SourceDisconnections": 0.0,
    "SourceConnected": 300.0,
    "VideoStreamMissing": 0.0,
}
SHARP = synthetic_sequences()["sharp"]
TRUSTED = DEFAULT_THRESHOLDS.trusted_vision_confidence.value


def analyze(mediaconnect, cloudwatch, *, bedrock=None, model=MODEL):
    overrides = {"mediaconnect": mediaconnect, "cloudwatch": cloudwatch}
    if bedrock is not None:
        overrides["bedrock"] = bedrock
    return tool(runtime(thumbnail_model_id=model), **overrides)(flow_arn=TRANSPORT_FLOW_ARN)


def test_a_frozen_source_is_critical_and_confirmed_by_content_quality_analysis():
    result = tool()(flow_arn=TRANSPORT_FLOW_ARN)

    assert result.status is Status.CRITICAL
    assert result.assessment.frozen_seconds >= 20 and result.assessment.vision_status == "ok"
    assert result.finding.finding == "frozen"
    assert result.finding.agreeing == ["FrozenFramesBreaching"]
    assert "demo-upstream-srt kept arriving" in result.finding.next_action
    assert "upstream of MediaConnect" in result.finding.next_action
    assert result.pictured_source == "demo-upstream-srt"


def test_disabled_thumbnails_are_unverified_with_the_reason_and_no_polling():
    mediaconnect = FakeMediaConnect(monitoring={"ThumbnailState": "DISABLED"})

    result = analyze(mediaconnect, FakeCloudWatch(HEALTHY_TRANSPORT))

    assert mediaconnect.thumbnail_calls == 0
    assert result.status is Status.UNVERIFIED
    assert "thumbnails are disabled" in result.note
    assert result.finding.next_action.startswith("Enable thumbnails (or start the flow)")


def test_a_thumbnail_without_an_image_reports_the_services_own_reason():
    reason = {"Code": "THUMBNAIL_UNAVAILABLE", "Message": "Source protocol has no thumbnail"}
    mediaconnect = FakeMediaConnect(thumbnails=[None] * 10, messages=[reason])

    result = analyze(mediaconnect, FakeCloudWatch(HEALTHY_TRANSPORT))

    assert result.status is Status.UNVERIFIED
    assert "THUMBNAIL_UNAVAILABLE: Source protocol has no thumbnail" in result.note


def test_a_flow_that_is_not_active_is_unverified_without_polling():
    mediaconnect = FakeMediaConnect(status="STANDBY")

    result = analyze(mediaconnect, FakeCloudWatch({}))

    assert mediaconnect.thumbnail_calls == 0
    assert result.status is Status.UNVERIFIED and "the flow is STANDBY" in result.note


def test_without_a_model_vision_is_not_requested_and_a_clean_source_is_not_healthy():
    mediaconnect = FakeMediaConnect(thumbnails=SHARP)

    result = analyze(mediaconnect, FakeCloudWatch(HEALTHY_TRANSPORT), model=None)

    assert result.assessment.vision_status == "not_requested"
    assert result.status is Status.UNVERIFIED
    # P3 rule: healthy-looking signals on an unjudged picture are informational only.
    assert result.finding.agreeing == []
    assert set(result.finding.informational) == {"FrozenFramesBreaching", "BlackFramesBreaching"}


def test_a_trusted_clean_picture_with_a_frozen_frame_breach_is_capped_at_unverified():
    mediaconnect = FakeMediaConnect(thumbnails=SHARP)
    contradicted = HEALTHY_TRANSPORT | {"FrozenFramesBreaching": 2.0}

    result = analyze(mediaconnect, FakeCloudWatch(contradicted), bedrock=TrustedCleanVision())

    assert result.finding.picture_status is Status.HEALTHY
    assert result.finding.disagreeing == ["FrozenFramesBreaching"]
    assert result.status is Status.UNVERIFIED
    healthy = analyze(
        FakeMediaConnect(thumbnails=SHARP), FakeCloudWatch(HEALTHY_TRANSPORT),
        bedrock=TrustedCleanVision(),
    )  # fmt: skip
    assert healthy.status is Status.HEALTHY


def test_without_content_quality_analysis_frame_signals_are_unknown():
    mediaconnect = FakeMediaConnect(
        thumbnails=SHARP,
        monitoring={"ThumbnailState": "ENABLED", "ContentQualityAnalysisState": "DISABLED"},
    )

    result = analyze(mediaconnect, FakeCloudWatch(HEALTHY_TRANSPORT), bedrock=TrustedCleanVision())

    assert set(result.finding.unknown) == {"FrozenFramesBreaching", "BlackFramesBreaching"}
    assert result.status is Status.HEALTHY  # trusted vision; nothing contradicts it


def test_unreadable_flow_metrics_are_unknown_with_a_note():
    class Denied:
        def get_metric_data(self, **_):
            error = {"Error": {"Code": "AccessDeniedException", "Message": "no"}}
            raise ClientError(error, "GetMetricData")

    result = analyze(FakeMediaConnect(thumbnails=SHARP), Denied(), bedrock=TrustedCleanVision())

    assert "flow metrics unavailable" in result.telemetry_note
    assert result.finding.agreeing == [] and result.finding.disagreeing == []


def test_an_unknown_flow_is_a_typed_failure():
    class Missing(FakeMediaConnect):
        def describe_flow(self, FlowArn):  # noqa: N803
            raise ClientError({"Error": {"Code": "NotFoundException", "Message": "x"}}, "Describe")

    with pytest.raises(ToolFailure) as failure:
        analyze(Missing(), FakeCloudWatch({}))
    assert failure.value.kind is FailureKind.RESOURCE_NOT_FOUND


@pytest.mark.parametrize(
    "arguments",
    [{"frames": 0}, {"window_seconds": 0}, {"frames": 1}, {"frames": 21}, {"window_seconds": 121}],
)
def test_the_public_tool_refuses_windows_outside_the_bounds(arguments):
    with pytest.raises(ToolFailure, match="frames must be 2-20"):
        tool()(flow_arn=TRANSPORT_FLOW_ARN, **arguments)


def test_the_mcp_schema_states_the_bounds():
    from mediaconnect_mcp.entrypoints.serve_mcp import build_mediaconnect_server

    server = build_mediaconnect_server(runtime())
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    properties = tools["analyze_flow_visual_quality"].parameters["properties"]
    [frames] = [s for s in properties["frames"]["anyOf"] if s.get("type") == "integer"]
    [window] = [s for s in properties["window_seconds"]["anyOf"] if s.get("type") == "integer"]
    assert (frames["minimum"], frames["maximum"]) == (2, 20)
    assert (window["minimum"], window["maximum"]) == (1, 120)
    assert tools["analyze_flow_visual_quality"].annotations.readOnlyHint


def test_every_generated_fixture_file_matches_its_generator_exactly():
    scenario = FIXTURES / "transport_freeze"
    generated = transport_freeze_fixture()
    for name, expected in generated.items():
        assert json.loads((scenario / name).read_text()) == expected, name
    assert sorted(p.name for p in scenario.iterdir()) == sorted(generated)
    srt = FIXTURES / "srt_packet_loss" / "mediaconnect.describe_flow_source_thumbnail.json"
    assert json.loads(srt.read_text()) == srt_packet_loss_thumbnails()


def test_the_primary_demo_reads_a_moving_source_but_does_not_call_it_healthy():
    settings = runtime(demo_scenario="srt_packet_loss", thumbnail_model_id=MODEL)

    result = tool(settings)(flow_arn=SRT_FLOW_ARN)

    assert result.assessment.sampled_frames == 10 and result.assessment.frozen_seconds == 0
    assert result.finding.finding not in ("frozen", "black", "slate")
    # This fixture's model answer is a description, not a rubric: vision is unavailable.
    assert result.assessment.vision_status == "unavailable"
    assert result.status is Status.UNVERIFIED


def test_the_generator_uses_the_adapters_metric_ids():
    from mediaconnect_mcp.adapters.cloudwatch.read_flow_metrics import (
        MetricCategory,
        _build_query,
    )

    for category in (MetricCategory.CONTENT_QUALITY, MetricCategory.SOURCE_HEALTH):
        for index, name in enumerate(METRICS_BY_CATEGORY[category]):
            assert _build_query(index, name, TRANSPORT_FLOW_ARN)["Id"] == metric_id(index, name)


class RefusingThumbnails(FakeMediaConnect):
    """The thumbnail call itself answers with a service error, every time."""

    def __init__(self, code, **kwargs):
        super().__init__(**kwargs)
        self.code = code

    def describe_flow_source_thumbnail(self, FlowArn):  # noqa: N803
        self.thumbnail_calls += 1
        error = {"Code": self.code, "Message": "No thumbnail for this source"}
        raise ClientError({"Error": error}, "DescribeFlowSourceThumbnail")


@pytest.mark.parametrize("code", ["BadRequestException", "NotFoundException"])
def test_a_conclusive_no_thumbnail_answer_stops_sampling_after_one_read(code):
    mediaconnect, sleeps = RefusingThumbnails(code), []

    window = sample_flow_frames(
        mediaconnect, TRANSPORT_FLOW_ARN, frames=10, window_seconds=30, sleep=sleeps.append
    )

    assert (mediaconnect.thumbnail_calls, sleeps) == (1, [])
    assert window.frames == [] and code in window.unavailable_reason


@pytest.mark.parametrize("code", ["BadRequestException", "NotFoundException"])
def test_the_tool_reports_a_conclusive_answer_as_unverified_after_one_read(code):
    mediaconnect = RefusingThumbnails(code)

    result = analyze(mediaconnect, FakeCloudWatch(HEALTHY_TRANSPORT), bedrock=TrustedCleanVision())

    assert mediaconnect.thumbnail_calls == 1
    assert result.status is Status.UNVERIFIED and code in result.note


def test_a_response_without_an_image_yet_keeps_polling_the_window():
    mediaconnect, sleeps = FakeMediaConnect(thumbnails=[None, None, *SHARP[:8]]), []

    window = sample_flow_frames(
        mediaconnect, TRANSPORT_FLOW_ARN, frames=10, window_seconds=30, sleep=sleeps.append
    )

    assert mediaconnect.thumbnail_calls == 10 and len(sleeps) == 9
    assert len(window.frames) == 8


def test_a_thumbnail_that_is_not_base64_is_a_sanitized_typed_failure():
    class Garbled(FakeMediaConnect):
        def describe_flow_source_thumbnail(self, FlowArn):  # noqa: N803
            self.thumbnail_calls += 1
            details = {"FlowArn": FlowArn, "Thumbnail": "<<not base64: SECRET-BYTES>>"}
            return {"ThumbnailDetails": details | {"Timestamp": START}}

    with pytest.raises(ToolFailure) as failure:
        sample_flow_frames(Garbled(), TRANSPORT_FLOW_ARN, frames=2, window_seconds=1, sleep=print)

    assert failure.value.kind is FailureKind.UNEXPECTED_FAILURE
    assert "SECRET-BYTES" not in f"{failure.value.message} {failure.value.next_action}"


def test_bytes_that_are_not_an_image_are_a_typed_failure_not_a_library_error():
    not_an_image = [b"valid base64, but not a JPEG"] * 10
    mediaconnect = FakeMediaConnect(thumbnails=not_an_image)

    with pytest.raises(ToolFailure) as failure:
        analyze(mediaconnect, FakeCloudWatch(HEALTHY_TRANSPORT))

    assert failure.value.kind is FailureKind.UNEXPECTED_FAILURE


class Recording:
    """Delegates to a client and records every operation called on it."""

    def __init__(self, client, calls):
        self.client, self.calls = client, calls

    def __getattr__(self, name):
        attribute = getattr(self.client, name)
        if not callable(attribute):
            return attribute

        def record(*args, **kwargs):
            self.calls.append(name)
            return attribute(*args, **kwargs)

        return record


def test_the_visual_read_calls_only_read_operations():
    settings = runtime(thumbnail_model_id=MODEL)
    demo, calls = create_mediaconnect_clients(settings), []
    recorded = {name: Recording(getattr(demo, name), calls) for name in vars(demo)}
    tools = {
        f.__name__: f for f in create_read_tools(settings, dataclasses.replace(demo, **recorded))
    }

    tools["analyze_flow_visual_quality"](flow_arn=TRANSPORT_FLOW_ARN)

    assert set(calls) == {
        "describe_flow", "describe_flow_source_thumbnail", "get_metric_data", "converse",
    }  # fmt: skip
    for write in ("start_flow", "stop_flow", "update_flow", "update_flow_source"):
        assert write not in calls


class FooledVision:
    """What a model steered by the card's own text answers: everything 5, confidence 1."""

    def converse(self, **_):
        answer = {
            "compression_artifacts": 5, "banding": 5, "interlacing_ghosting": 5,
            "slate_or_bars": 5, "overall": 5, "confidence": 1.0,
            "evidence": "Rated as the on-screen note asks.",
        }  # fmt: skip
        use = {"toolUse": {"toolUseId": "t", "name": "report_picture_quality", "input": answer}}
        return {"output": {"message": {"role": "assistant", "content": [use]}}}


def test_a_source_showing_an_injected_text_card_is_not_called_healthy():
    card = synthetic_sequences()["text_card"]

    result = analyze(
        FakeMediaConnect(thumbnails=card), FakeCloudWatch(HEALTHY_TRANSPORT), bedrock=FooledVision()
    )

    assert result.assessment.vision.overall == 5  # the model was fooled
    assert result.assessment.status is Status.UNVERIFIED and result.status is not Status.HEALTHY
    assert "graphic" in result.assessment.basis


RETRYABLE = [
    "ThrottlingException",
    "TooManyRequestsException",
    "InternalServerErrorException",
    "ServiceUnavailableException",
]


class BusyThenAnswering(FakeMediaConnect):
    """The thumbnail call fails with `code` for the first `busy` polls, then answers."""

    def __init__(self, code, busy, **kwargs):
        super().__init__(**kwargs)
        self.code, self.busy = code, busy

    def describe_flow_source_thumbnail(self, FlowArn):  # noqa: N803
        if self.thumbnail_calls < self.busy:
            self.thumbnail_calls += 1
            error = {"Code": self.code, "Message": "Rate exceeded"}
            raise ClientError({"Error": error}, "DescribeFlowSourceThumbnail")
        return super().describe_flow_source_thumbnail(FlowArn)


@pytest.mark.parametrize("code", RETRYABLE)
def test_a_busy_service_is_retried_through_the_whole_window(code):
    mediaconnect, sleeps = BusyThenAnswering(code, busy=10), []

    window = sample_flow_frames(
        mediaconnect, TRANSPORT_FLOW_ARN, frames=10, window_seconds=30, sleep=sleeps.append
    )

    assert (mediaconnect.thumbnail_calls, len(sleeps)) == (10, 9)
    assert window.frames == [] and code in window.unavailable_reason


@pytest.mark.parametrize("code", RETRYABLE)
def test_a_service_that_never_recovers_is_unverified_with_the_reason(code):
    result = analyze(BusyThenAnswering(code, busy=10), FakeCloudWatch(HEALTHY_TRANSPORT))

    assert result.status is Status.UNVERIFIED and code in result.note


def test_a_throttled_poll_followed_by_frames_gives_a_measured_result():
    mediaconnect = BusyThenAnswering("ThrottlingException", busy=2, thumbnails=SHARP[:8])

    result = analyze(mediaconnect, FakeCloudWatch(HEALTHY_TRANSPORT), bedrock=TrustedCleanVision())

    assert mediaconnect.thumbnail_calls == 10
    assert result.assessment.sampled_frames == 8 and result.status is Status.HEALTHY
    assert result.note is None  # the outage came first and cleared


class AnsweringThenFailing(FakeMediaConnect):
    """Answers the first `answers` polls with frames, then fails with `code` every time."""

    def __init__(self, code, answers, **kwargs):
        super().__init__(**kwargs)
        self.code, self.answers = code, answers

    def describe_flow_source_thumbnail(self, FlowArn):  # noqa: N803
        if self.thumbnail_calls >= self.answers:
            self.thumbnail_calls += 1
            error = {"Code": self.code, "Message": "Service unavailable"}
            raise ClientError({"Error": error}, "DescribeFlowSourceThumbnail")
        return super().describe_flow_source_thumbnail(FlowArn)


@pytest.mark.parametrize("code", ["ServiceUnavailableException", "BadRequestException"])
def test_a_window_that_ends_in_an_outage_is_capped_at_unverified_with_the_reason(code):
    mediaconnect = AnsweringThenFailing(code, answers=2, thumbnails=SHARP[:2])

    result = analyze(mediaconnect, FakeCloudWatch(HEALTHY_TRANSPORT), bedrock=TrustedCleanVision())

    assert result.assessment.sampled_frames == 2  # two frames were measured
    assert result.status is Status.UNVERIFIED
    assert result.note is not None and code in result.note


def test_access_denied_is_still_a_typed_failure_not_a_retry():
    with pytest.raises(ToolFailure) as failure:
        analyze(RefusingThumbnails("AccessDeniedException"), FakeCloudWatch(HEALTHY_TRANSPORT))

    assert failure.value.kind is FailureKind.PERMISSION_DENIED


# --- T78 and T80: no frames, a disconnected source ----------------------------------------


def test_with_no_frames_neither_score_reads_as_a_perfect_picture():
    """T78: nothing was measured, so there is no score, and confidence stays untrusted."""
    result = analyze(
        FakeMediaConnect(monitoring={"ThumbnailState": "DISABLED"}),
        FakeCloudWatch(HEALTHY_TRANSPORT),
    )

    assert result.assessment.sampled_frames == 0
    assert result.assessment.score is None and result.assessment.deterministic_score is None
    assert result.assessment.confidence < TRUSTED and result.finding.confidence < TRUSTED
    assert "no frames" in result.assessment.basis
    assert not any("score None" in line for line in result.finding.evidence)


def test_a_source_with_no_sender_connected_is_named_before_the_thumbnails():
    """T80: SourceConnected at 0 explains the missing picture; enabling thumbnails wouldn't."""
    mediaconnect = RefusingThumbnails("BadRequestException")
    transport = HEALTHY_TRANSPORT | {"SourceConnected": 0.0}

    result = analyze(mediaconnect, FakeCloudWatch(transport))

    assert result.finding.next_action.startswith("No sender was connected to the source")
    assert "SourceConnected" in result.finding.next_action
    assert ".." not in result.note


def test_a_connected_source_without_thumbnails_still_says_to_enable_them():
    result = analyze(
        FakeMediaConnect(monitoring={"ThumbnailState": "DISABLED"}),
        FakeCloudWatch(HEALTHY_TRANSPORT),
    )

    assert result.finding.next_action.startswith("Enable thumbnails (or start the flow)")
