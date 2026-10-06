"""Fusion: agreeing telemetry raises confidence, disagreeing lowers it, missing is unknown."""

from datetime import UTC, datetime, timedelta

from generate_quality_fixtures import synthetic_sequences

from media_ops_video_quality.assess_window import SampledFrame, Status, assess_window
from media_ops_video_quality.fuse_with_telemetry import (
    Finding,
    PipelineTelemetry,
    fuse_with_telemetry,
)
from media_ops_video_quality.quality_thresholds import DEFAULT_THRESHOLDS

AGREE_STEP = DEFAULT_THRESHOLDS.telemetry_agree_step.value
DISAGREE_STEP = DEFAULT_THRESHOLDS.telemetry_disagree_step.value

SEQUENCES = synthetic_sequences()
START = datetime(2026, 10, 6, 14, 32, tzinfo=UTC)


def window(name, frames=None):
    chosen = SEQUENCES[name] if frames is None else SEQUENCES[name][:frames]
    sampled = [
        SampledFrame(taken_at=START + timedelta(seconds=3 * n), jpeg=f)
        for n, f in enumerate(chosen)
    ]
    return assess_window(sampled, requested_frames=10)  # no vision: confidence 0.5


def fuse(name, **telemetry):
    return fuse_with_telemetry("0", window(name), PipelineTelemetry(pipeline_id="0", **telemetry))


def test_a_freeze_confirmed_by_mqcs_raises_confidence():
    result = fuse("frozen", mqcs_freeze_min=30.0, fill_msec_max=0, input_loss_seconds=0)
    assert result.finding is Finding.FROZEN
    assert result.agreeing == ["MqcsFreezeFrameDetected"]
    assert result.confidence == 0.5 + AGREE_STEP
    assert "kept arriving over the last 15 minutes" in result.next_action


def test_a_freeze_contradicted_by_mqcs_lowers_confidence_and_says_so():
    result = fuse("frozen", mqcs_freeze_min=100.0)
    assert result.disagreeing == ["MqcsFreezeFrameDetected"]
    assert result.confidence == 0.5 - DISAGREE_STEP
    assert result.next_action.startswith("Signals disagree")


def test_a_signal_that_was_not_emitted_is_unknown_and_leaves_confidence_alone():
    result = fuse("frozen")
    assert result.unknown == ["MqcsFreezeFrameDetected"]
    assert result.agreeing == result.disagreeing == []
    assert result.confidence == 0.5
    assert "MqcsFreezeFrameDetected min (last 15 min): not emitted" in result.evidence


def test_a_clean_picture_with_an_encoder_freeze_is_a_disagreement():
    result = fuse("sharp", mqcs_freeze_min=40.0, mqcs_black_min=100.0)
    assert result.disagreeing == ["MqcsFreezeFrameDetected"]
    assert result.agreeing == [] and result.informational == ["MqcsBlackFrameDetected"]
    assert result.status is Status.UNVERIFIED  # no vision: never healthy


def test_black_and_slate_point_upstream_when_the_input_is_starved():
    black = fuse("black", mqcs_black_min=0.0, input_loss_seconds=120.0, active_input="primary-srt")
    assert black.finding is Finding.BLACK and black.agreeing == ["MqcsBlackFrameDetected"]
    assert "observed on input primary-srt within the last 15 minutes" in black.next_action
    slate = fuse("slate", fill_msec_max=60000.0)
    assert slate.finding is Finding.SLATE and slate.agreeing == ["FillMsec/InputLossSeconds"]


def test_a_single_frame_is_unverified_whatever_the_telemetry_says():
    result = fuse_with_telemetry(
        "0", window("sharp", frames=1), PipelineTelemetry(pipeline_id="0", mqcs_freeze_min=100.0)
    )
    assert result.finding is Finding.UNVERIFIED
    assert result.status is Status.UNVERIFIED
    assert result.next_action.startswith("Enable thumbnails")


def test_an_unverified_picture_gains_no_confidence_from_agreeing_telemetry():
    # No vision: a clean window is UNVERIFIED. The encoder reporting no freeze and no black
    # agrees, but agreement can't verify a picture nobody judged; a contradiction still lowers.
    agreeing = fuse("sharp", mqcs_freeze_min=100.0, mqcs_black_min=100.0)
    assert agreeing.finding is Finding.UNVERIFIED
    assert agreeing.agreeing == []
    assert agreeing.informational == ["MqcsFreezeFrameDetected", "MqcsBlackFrameDetected"]
    assert agreeing.confidence == 0.5
    contradicted = fuse("sharp", mqcs_freeze_min=40.0, mqcs_black_min=100.0)
    assert contradicted.confidence == 0.5 - DISAGREE_STEP


# --- GPT review of P3 (b712391): each blocker reproduced as a test --------------------------


def trusted_window(name, *, overall=5, interlacing=5, banding=5, confidence=0.9):
    from media_ops_video_quality.assess_window import VisionScores

    vision = VisionScores(
        compression_artifacts=5, banding=banding, interlacing_ghosting=interlacing,
        slate_or_bars=5, overall=overall, confidence=confidence, evidence="model evidence",
    )  # fmt: skip
    sampled = [
        SampledFrame(taken_at=START + timedelta(seconds=3 * n), jpeg=f)
        for n, f in enumerate(SEQUENCES[name])
    ]
    return assess_window(sampled, requested_frames=10, vision=vision, vision_status="ok")


def test_1_unknown_input_telemetry_makes_no_root_cause_claim():
    result = fuse("frozen")  # no fill, no input-loss data
    assert "still arrives" not in result.next_action
    assert "stopped delivering" not in result.next_action
    assert "input health is unknown" in result.next_action.lower()


def test_1_input_loss_is_reported_as_observed_in_the_metric_window_not_as_current():
    result = fuse("frozen", mqcs_freeze_min=30.0, input_loss_seconds=4.0, active_input="srt")
    assert "within the last 15 minutes" in result.next_action
    flowing = fuse("frozen", mqcs_freeze_min=30.0, fill_msec_max=0, input_loss_seconds=0)
    assert "last 15 minutes" in flowing.next_action


def test_2_a_defect_found_by_trusted_vision_is_a_picture_problem_not_unverified():
    assessment = trusted_window("sharp", overall=1, interlacing=1, banding=1)
    assert assessment.status is Status.CRITICAL and assessment.vision_status == "ok"

    result = fuse_with_telemetry("0", assessment, PipelineTelemetry(pipeline_id="0"))

    assert result.finding is Finding.PICTURE_PROBLEM
    assert "Enable thumbnails" not in result.next_action
    assert any("model evidence" in line for line in result.evidence)


def test_3_an_encoder_freeze_on_a_trusted_clean_picture_is_never_healthy():
    assessment = trusted_window("sharp")
    assert assessment.status is Status.HEALTHY

    result = fuse_with_telemetry(
        "0",
        assessment,
        PipelineTelemetry(pipeline_id="0", mqcs_freeze_min=30.0, mqcs_black_min=100.0),
    )

    assert result.disagreeing == ["MqcsFreezeFrameDetected"]
    assert result.picture_status is Status.HEALTHY
    assert result.status is Status.UNVERIFIED  # fused: fail toward doubt
    # The unrelated "no black" agreement does not offset the contradiction.
    assert result.confidence == round(assessment.confidence - DISAGREE_STEP, 2)


def test_4_an_unverified_picture_publishes_no_agreement():
    result = fuse("sharp", mqcs_freeze_min=100.0, mqcs_black_min=100.0)
    assert result.finding is Finding.UNVERIFIED
    assert result.agreeing == []
    assert result.informational == ["MqcsFreezeFrameDetected", "MqcsBlackFrameDetected"]
