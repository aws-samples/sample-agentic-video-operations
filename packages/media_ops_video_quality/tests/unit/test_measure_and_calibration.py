"""Each synthetic sequence lands clearly on its side of every threshold (calibration gate)."""

from generate_quality_fixtures import draw_pattern, encode, synthetic_sequences
from PIL import ImageFilter

from media_ops_video_quality.compare_frames import compare_frames
from media_ops_video_quality.measure_frame import measure_frame
from media_ops_video_quality.quality_thresholds import DEFAULT_THRESHOLDS as T
from media_ops_video_quality.quality_thresholds import Threshold

SEQUENCES = synthetic_sequences()


def metric(name, field):
    return [getattr(measure_frame(frame), field) for frame in SEQUENCES[name]]


def changes(name):
    frames = SEQUENCES[name]
    return [
        compare_frames(a, b).mean_abs_difference for a, b in zip(frames, frames[1:], strict=False)
    ]


def test_sharpness_separates_sharp_from_blurred_by_a_wide_margin():
    blur = T.blurred_below_sharpness.value
    assert min(metric("sharp", "sharpness")) > 2 * blur
    assert max(metric("blurred", "sharpness")) < blur / 2


def test_blockiness_estimate_separates_heavy_compression_from_clean_and_blurred():
    blocky = T.blocky_above_excess.value
    assert min(metric("blocky", "blockiness_estimate")) > 1.5 * blocky
    for clean in ("sharp", "blurred", "black", "slate"):
        assert max(metric(clean, "blockiness_estimate")) < blocky / 2, clean


def test_black_and_flat_frames_are_far_below_their_thresholds():
    assert max(metric("black", "luma_mean")) < T.black_below_luma_mean.value - 3
    assert max(metric("slate", "luma_stddev")) < T.flat_below_luma_stddev.value / 2
    assert min(metric("sharp", "luma_stddev")) > 5 * T.flat_below_luma_stddev.value


def test_freeze_and_motion_are_separated_and_cuts_are_scene_changes():
    frozen = T.frozen_below_difference.value
    assert max(changes("frozen")) < frozen / 4
    assert min(changes("sharp") + changes("blurred") + changes("blocky")) > 1.5 * frozen
    cut = compare_frames(SEQUENCES["sharp"][0], SEQUENCES["slate"][0]).mean_abs_difference
    assert cut > T.scene_change_above_difference.value
    assert max(changes("sharp")) < T.scene_change_above_difference.value / 5


def test_the_thresholds_hold_at_thumbnail_size_320x180():
    small = draw_pattern(3).resize((320, 180))
    sharp = measure_frame(encode(small))
    blurred = measure_frame(encode(small.filter(ImageFilter.GaussianBlur(2))))
    blocky = measure_frame(encode(small, quality=5))
    assert sharp.sharpness > T.blurred_below_sharpness.value > blurred.sharpness
    assert blocky.blockiness_estimate > T.blocky_above_excess.value > sharp.blockiness_estimate
    assert blurred.blockiness_estimate < T.blocky_above_excess.value  # blur must not read blocky


def every_threshold(thresholds):
    for value in thresholds.__dict__.values():
        if isinstance(value, Threshold):
            yield value
        elif isinstance(value, dict):
            yield from value.values()


def test_every_decision_value_states_its_rationale():
    found = list(every_threshold(T))
    # 7 measurements, including the graphic-palette check, + 5 penalty weights + 3 status floors
    # + the vision trust level + 4 window-confidence values + 2 telemetry steps
    # + the finding majority share
    assert len(found) == 23
    assert all(isinstance(t, Threshold) and len(t.rationale) > 40 for t in found)
    assert {
        name for name, value in T.__dict__.items() if not isinstance(value, Threshold | dict)
    } == set()
