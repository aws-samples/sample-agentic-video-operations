"""analyze_channel_visual_quality: sampling, frozen output, and the honest unknown states."""

import base64
import dataclasses
from pathlib import Path

import pytest

from media_ops_contracts.tool_failure import ToolFailure
from media_ops_video_quality.assess_window import Status
from media_ops_video_quality.quality_thresholds import DEFAULT_THRESHOLDS
from medialive_mcp.adapters.media_live.sample_channel_frames import sample_channel_frames
from medialive_mcp.bootstrap.create_medialive_clients import create_medialive_clients
from medialive_mcp.settings.runtime_settings import RuntimeSettings
from medialive_mcp.tool_surface.create_read_tools import create_read_tools

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures"
MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


def tool(**settings):
    values = {"demo": True, "demo_scenario": "frozen_output", "fixtures_dir": FIXTURES} | settings
    runtime = RuntimeSettings(**values)
    tools = {f.__name__: f for f in create_read_tools(runtime, create_medialive_clients(runtime))}
    return tools["analyze_channel_visual_quality"]


def test_a_frozen_pipeline_is_critical_and_the_moving_one_healthy():
    result = tool(thumbnail_model_id=MODEL)(channel_id="1234567")
    by_pipeline = {p.pipeline_id: p.assessment for p in result.pipelines}
    assert result.status == Status.CRITICAL
    assert by_pipeline["0"].status == Status.CRITICAL
    assert by_pipeline["0"].frozen_seconds >= 20
    assert by_pipeline["1"].status == Status.HEALTHY
    assert all(a.vision_status == "ok" for a in by_pipeline.values())


def test_without_a_vision_model_a_clean_pipeline_is_unverified_not_healthy():
    result = tool(thumbnail_model_id=None)(channel_id="1234567", pipeline_id="1")
    [pipeline] = result.pipelines
    assert pipeline.assessment.vision_status == "not_requested"
    assert pipeline.assessment.status == Status.UNVERIFIED
    # The channel is still the worst pipeline's: the frozen pipeline 0 is CRITICAL.
    assert (result.status, result.worst_pipeline_id) == (Status.CRITICAL, "0")


class FakeMediaLive:
    def __init__(self, stamps):
        self.stamps = list(stamps)
        self.calls = 0

    def describe_thumbnails(self, **_):
        self.calls += 1
        stamp = self.stamps.pop(0)
        if stamp is None:
            return {"ThumbnailDetails": []}
        body = base64.b64encode(b"\xff\xd8 not decoded here").decode()
        return {"ThumbnailDetails": [{"Thumbnails": [{"Body": body, "TimeStamp": stamp}]}]}


def test_the_sampler_spaces_its_polls_and_drops_repeated_thumbnails():
    waits = []
    medialive = FakeMediaLive(
        ["2026-10-06T14:32:00Z", "2026-10-06T14:32:00Z", "2026-10-06T14:32:05Z"]
    )
    sampled = sample_channel_frames(
        medialive, "1", ["0"], frames=3, window_seconds=10, sleep=waits.append
    )
    assert waits == [5.0, 5.0]
    assert len(sampled["0"]) == 2  # the unrefreshed thumbnail counts once


def test_a_pipeline_without_thumbnails_yields_no_frames_and_reads_unverified():
    medialive = FakeMediaLive([None, None])
    sampled = sample_channel_frames(
        medialive, "1", ["0"], frames=2, window_seconds=2, sleep=lambda s: None
    )
    assert sampled == {"0": []}


def test_windows_beyond_the_bounds_are_refused():
    for frames, window in ((1, 10), (21, 10), (8, 121)):
        with pytest.raises(ToolFailure):
            sample_channel_frames(
                FakeMediaLive([]),
                "1",
                ["0"],
                frames=frames,
                window_seconds=window,
                sleep=lambda s: None,
            )


def test_every_generated_fixture_file_matches_its_generator_exactly():
    import json

    from generate_quality_fixtures import frozen_output_fixture

    scenario = FIXTURES / "frozen_output"
    generated = frozen_output_fixture()
    for name, expected in generated.items():
        assert json.loads((scenario / name).read_text()) == expected, name
    # The one copied file is the input_loss channel, byte for byte.
    channel = "medialive.describe_channel.json"
    assert (scenario / channel).read_text() == (FIXTURES / "input_loss" / channel).read_text()
    assert sorted(p.name for p in scenario.iterdir()) == sorted([*generated, channel])


def test_an_unknown_pipeline_is_refused():
    with pytest.raises(ToolFailure, match="no pipeline 7"):
        tool(thumbnail_model_id=MODEL)(channel_id="1234567", pipeline_id="7")


def test_the_frozen_pipeline_is_confirmed_by_the_encoders_freeze_signal():
    result = tool(thumbnail_model_id=MODEL)(channel_id="1234567")
    findings = {f.pipeline_id: f for f in result.findings}
    assert findings["0"].finding == "frozen"
    assert findings["0"].agreeing == ["MqcsFreezeFrameDetected"]
    assert "demo-primary-srt" in findings["0"].next_action
    assert findings["1"].finding == "no_picture_problem"
    assert result.telemetry_note is None


def test_unreadable_encoder_metrics_are_unknown_not_agreement(monkeypatch):
    from medialive_mcp.workflows import assess_channel_visual_quality as workflow

    def denied(*args, **kwargs):
        raise ToolFailure("PermissionDenied", "Not authorized for GetMetricData.", "Grant it.")

    monkeypatch.setattr(workflow, "read_metrics", denied)
    result = tool(thumbnail_model_id=MODEL)(channel_id="1234567")
    frozen = next(f for f in result.findings if f.pipeline_id == "0")
    assert frozen.agreeing == [] and frozen.unknown == ["MqcsFreezeFrameDetected"]
    assert "unavailable" in result.telemetry_note


# GPT review of P2 (cd2d3e2), blocker 1: the public bounds.
@pytest.mark.parametrize(
    "arguments",
    [{"frames": 0}, {"window_seconds": 0}, {"frames": 1}, {"frames": 21}, {"window_seconds": 121}],
)
def test_the_public_tool_refuses_windows_outside_the_bounds(arguments):
    with pytest.raises(ToolFailure, match="frames must be 2-20"):
        tool(thumbnail_model_id=MODEL)(channel_id="1234567", **arguments)


@pytest.mark.parametrize(
    "arguments",
    [{"frames": 2}, {"frames": 20}, {"window_seconds": 1}, {"window_seconds": 120}, {}],
)
def test_the_public_tool_passes_bounds_and_defaults_through(arguments, monkeypatch):
    import medialive_mcp.tool_surface.create_read_tools as surface

    seen = {}
    monkeypatch.setattr(surface, "assess_channel_visual_quality", lambda *_, **kw: seen.update(kw))
    tool(thumbnail_model_id=MODEL)(channel_id="1234567", **arguments)
    assert seen["frames"] == arguments.get("frames", 10)
    assert seen["window_seconds"] == arguments.get("window_seconds", 30)


def test_the_mcp_schema_states_the_bounds():
    import asyncio

    from medialive_mcp.entrypoints.serve_mcp import build_mcp_server

    runtime = RuntimeSettings(demo=True, demo_scenario="frozen_output", fixtures_dir=FIXTURES)
    server = build_mcp_server(runtime, create_medialive_clients(runtime))
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    properties = tools["analyze_channel_visual_quality"].parameters["properties"]
    [frames] = [s for s in properties["frames"]["anyOf"] if s.get("type") == "integer"]
    [window] = [s for s in properties["window_seconds"]["anyOf"] if s.get("type") == "integer"]
    assert (frames["minimum"], frames["maximum"]) == (2, 20)
    assert (window["minimum"], window["maximum"]) == (1, 120)


# GPT review of P2, blocker 2: one pipeline's answer must not depend on the request shape.
def test_asking_for_one_pipeline_scores_every_pipeline_and_keeps_the_worst_status():
    unfiltered = tool(thumbnail_model_id=MODEL)(channel_id="1234567")
    filtered = tool(thumbnail_model_id=MODEL)(channel_id="1234567", pipeline_id="1")

    [only] = filtered.pipelines
    [same] = [p for p in unfiltered.pipelines if p.pipeline_id == "1"]
    assert only.pipeline_id == "1"
    assert only.assessment == same.assessment
    assert only.assessment.status == Status.HEALTHY
    assert filtered.status == unfiltered.status == Status.CRITICAL  # capped by pipeline 0
    assert filtered.worst_pipeline_id == "0"


# GPT review of P3, blocker 5: no configured model is "not requested", not "unavailable".
def test_without_a_model_vision_is_not_requested_and_with_a_failing_one_unavailable():
    unconfigured = tool(thumbnail_model_id=None)(channel_id="1234567")
    assert {p.assessment.vision_status for p in unconfigured.pipelines} == {"not_requested"}

    import dataclasses

    from botocore.exceptions import ClientError

    class FailingBedrock:
        def converse(self, **_):
            error = {"Error": {"Code": "ThrottlingException", "Message": "slow down"}}
            raise ClientError(error, "Converse")

    runtime = RuntimeSettings(
        demo=True, demo_scenario="frozen_output", fixtures_dir=FIXTURES, thumbnail_model_id=MODEL
    )
    clients = dataclasses.replace(create_medialive_clients(runtime), bedrock=FailingBedrock())
    tools = {f.__name__: f for f in create_read_tools(runtime, clients)}
    attempted = tools["analyze_channel_visual_quality"](channel_id="1234567")
    assert {p.assessment.vision_status for p in attempted.pipelines} == {"unavailable"}


# GPT review of P3, blocker 3 at channel level: the channel reads the fused status.
def test_an_encoder_freeze_keeps_a_clean_channel_from_reading_healthy(monkeypatch):
    from datetime import UTC, datetime, timedelta

    from generate_quality_fixtures import synthetic_sequences

    from media_ops_video_quality.assess_window import SampledFrame, VisionScores, assess_window
    from media_ops_video_quality.fuse_with_telemetry import PipelineTelemetry
    from medialive_mcp.workflows import assess_channel_visual_quality as workflow

    start = datetime(2026, 10, 6, 14, 32, tzinfo=UTC)
    frames = [
        SampledFrame(taken_at=start + timedelta(seconds=3 * n), jpeg=jpeg)
        for n, jpeg in enumerate(synthetic_sequences()["sharp"])
    ]
    vision = VisionScores(
        compression_artifacts=5, banding=5, interlacing_ghosting=5, slate_or_bars=5,
        overall=5, confidence=0.9, evidence="clean",
    )  # fmt: skip
    clean = assess_window(frames, requested_frames=10, vision=vision, vision_status="ok")
    monkeypatch.setattr(
        workflow,
        "assess_pipeline",
        lambda _c, pipeline, *_: workflow.PipelineVisualQuality(
            pipeline_id=pipeline, assessment=clean
        ),
    )
    telemetry = {
        "0": PipelineTelemetry(pipeline_id="0", mqcs_freeze_min=100.0, mqcs_black_min=100.0),
        "1": PipelineTelemetry(pipeline_id="1", mqcs_freeze_min=30.0, mqcs_black_min=100.0),
    }
    monkeypatch.setattr(workflow, "read_telemetry", lambda *_: (telemetry, None))

    result = tool(thumbnail_model_id=MODEL)(channel_id="1234567")

    findings = {f.pipeline_id: f for f in result.findings}
    assert findings["0"].status is Status.HEALTHY
    assert (findings["1"].picture_status, findings["1"].status) == (
        Status.HEALTHY,
        Status.UNVERIFIED,
    )
    assert (result.status, result.worst_pipeline_id) == (Status.UNVERIFIED, "1")


# --- T78 and T79: no frames, and stopping early only on a conclusive answer --------------


class CountingMediaLive:
    """The replayed channel with its description changed, counting thumbnail reads."""

    def __init__(self, replay, *, thumbnails=True, **channel_changes):
        self.replay, self.changes = replay, channel_changes
        self.thumbnails, self.thumbnail_calls = thumbnails, 0

    def describe_channel(self, **kwargs):
        return self.replay.describe_channel(**kwargs) | self.changes

    def describe_thumbnails(self, **kwargs):
        self.thumbnail_calls += 1
        if not self.thumbnails:  # enabled, but none has arrived yet
            return {"ThumbnailDetails": []}
        return self.replay.describe_thumbnails(**kwargs)

    def __getattr__(self, name):
        return getattr(self.replay, name)


def analyze_changed(*, thumbnails=True, **channel_changes):
    runtime = RuntimeSettings(demo=True, demo_scenario="frozen_output", fixtures_dir=FIXTURES)
    clients = create_medialive_clients(runtime)
    medialive = CountingMediaLive(clients.medialive, thumbnails=thumbnails, **channel_changes)
    clients = dataclasses.replace(clients, medialive=medialive)
    tools = {f.__name__: f for f in create_read_tools(runtime, clients)}
    return tools["analyze_channel_visual_quality"](channel_id="1234567"), medialive


DISABLED = {"EncoderSettings": {"ThumbnailConfiguration": {"State": "DISABLED"}}}
ENABLED = {"EncoderSettings": {"ThumbnailConfiguration": {"State": "AUTO"}}}
TRUSTED = DEFAULT_THRESHOLDS.trusted_vision_confidence.value


def test_with_no_frames_neither_score_reads_as_a_perfect_picture():
    """T78: nothing was measured, so there is no score, and confidence stays untrusted."""
    result, _ = analyze_changed(**DISABLED)

    for pipeline in result.pipelines:
        assessment = pipeline.assessment
        assert assessment.sampled_frames == 0 and assessment.status is Status.UNVERIFIED
        assert assessment.score is None and assessment.deterministic_score is None
        assert assessment.confidence < TRUSTED
    assert all(finding.confidence < TRUSTED for finding in result.findings)


def test_thumbnails_disabled_in_the_channel_stop_sampling_before_any_read():
    """T79: a conclusive answer, as MediaConnect's disabled thumbnails are."""
    result, medialive = analyze_changed(**DISABLED)

    assert medialive.thumbnail_calls == 0
    assert result.status is Status.UNVERIFIED
    assert all("disabled in the channel's configuration" in p.note for p in result.pipelines)


def test_a_channel_that_is_not_running_is_not_sampled():
    result, medialive = analyze_changed(State="IDLE", **ENABLED)

    assert medialive.thumbnail_calls == 0
    assert all("the channel is IDLE" in p.note for p in result.pipelines)


def test_enabled_thumbnails_that_have_not_arrived_yet_keep_polling_the_window():
    """Transient, not conclusive: a running channel with thumbnails on is sampled throughout."""
    result, medialive = analyze_changed(thumbnails=False, **ENABLED)

    frames = RuntimeSettings(demo=True, fixtures_dir=FIXTURES).visual_quality_frames
    pipelines = len(result.pipelines)
    assert medialive.thumbnail_calls == frames * pipelines
    assert all("none arrived" in p.note for p in result.pipelines)
