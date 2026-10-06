"""Window status: findings, freeze duration, never healthy without vision, confidence."""

from datetime import UTC, datetime, timedelta

from generate_quality_fixtures import synthetic_sequences

from media_ops_video_quality.assess_window import SampledFrame, Status, VisionScores, assess_window

SEQUENCES = synthetic_sequences()
START = datetime(2026, 10, 6, 14, 32, tzinfo=UTC)


def window(name, interval=3):
    return [
        SampledFrame(taken_at=START + timedelta(seconds=interval * n), jpeg=frame)
        for n, frame in enumerate(SEQUENCES[name])
    ]


def vision(overall, confidence=0.9):
    return VisionScores(
        compression_artifacts=overall, banding=overall, interlacing_ghosting=overall,
        slate_or_bars=overall, overall=overall, confidence=confidence, evidence="test",
    )  # fmt: skip


def assess(name, **kwargs):
    return assess_window(window(name), requested_frames=10, **kwargs)


def test_a_clean_window_with_an_agreeing_vision_verdict_is_healthy_and_confident():
    result = assess("sharp", vision=vision(5), vision_status="ok")
    assert result.status == Status.HEALTHY
    assert result.confidence == 1.0
    assert result.shares == {"frozen": 0, "black": 0, "flat": 0, "blurred": 0, "blocky": 0}


def test_without_a_vision_verdict_a_clean_window_is_unverified_never_healthy():
    for status in ("unavailable", "not_requested"):
        result = assess("sharp", vision_status=status)
        assert result.status == Status.UNVERIFIED, status
        assert result.deterministic_score == 100
        assert status in result.basis


def test_a_low_confidence_vision_verdict_does_not_make_a_window_healthy():
    result = assess("sharp", vision=vision(5, confidence=0.2), vision_status="ok")
    assert result.status == Status.UNVERIFIED


def test_an_untrusted_verdict_never_raises_confidence_but_can_lower_it():
    measurements_only = assess("sharp").confidence
    agreeing = assess("sharp", vision=vision(5, confidence=0.2), vision_status="ok").confidence
    disagreeing = assess("sharp", vision=vision(1, confidence=0.2), vision_status="ok").confidence
    assert measurements_only == agreeing == 0.5
    assert disagreeing < measurements_only


def test_vision_disagreeing_with_the_measurements_lowers_confidence():
    agree = assess("sharp", vision=vision(5), vision_status="ok")
    disagree = assess("sharp", vision=vision(1), vision_status="ok")
    assert disagree.confidence < agree.confidence
    assert disagree.confidence == 0.6
    assert disagree.status == Status.CRITICAL  # the worse view wins the score


def test_a_frozen_window_is_critical_and_measures_how_long():
    result = assess("frozen")
    assert result.status == Status.CRITICAL
    assert result.shares["frozen"] == 0.9  # every frame after the first
    assert result.frozen_seconds == 27


def test_black_and_slate_windows_are_critical_and_not_counted_as_frozen():
    for name, finding in (("black", "black"), ("slate", "flat")):
        result = assess(name)
        assert result.status == Status.CRITICAL, name
        assert result.shares[finding] == 1.0
        assert result.shares["frozen"] == 0.0


def test_blurred_and_blocky_windows_are_degraded():
    for name, finding in (("blurred", "blurred"), ("blocky", "blocky")):
        result = assess(name)
        assert result.shares[finding] == 1.0, name
        assert result.status == Status.DEGRADED, name


def test_a_cut_is_a_scene_change_not_a_freeze():
    frames = window("sharp")[:3] + [
        SampledFrame(taken_at=START + timedelta(seconds=9), jpeg=SEQUENCES["slate"][0])
    ]
    result = assess_window(frames, requested_frames=4)
    assert result.frames[-1].scene_change is True
    assert result.frames[-1].frozen is False


def test_fewer_than_two_distinct_frames_is_unverified():
    result = assess_window(
        window("sharp")[:1], requested_frames=10, vision=vision(5), vision_status="ok"
    )
    assert result.status == Status.UNVERIFIED
    assert result.sampled_frames == 1
