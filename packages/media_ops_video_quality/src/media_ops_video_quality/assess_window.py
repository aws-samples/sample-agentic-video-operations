"""Turn a window of sampled frames (and an optional vision verdict) into one assessment.

- Each frame is measured; consecutive frames are compared for freeze and scene changes.
- A static black frame counts as black and a static flat one as flat, never also as frozen.
- Without a trusted vision verdict the result is never HEALTHY: a clean deterministic view
  becomes UNVERIFIED, so an unavailable vision pass can never read as healthy.
- A trusted vision verdict agreeing with the measurements raises confidence and one
  disagreeing lowers it; an untrusted verdict can only lower it.
- The frames reach the vision model as pictures, on-screen text included, and one rubric
  call sees them all, so a single frame of text can steer the verdict and its confidence.
  So if any frame is a detectable graphic (a card, slate or caption screen: a concentrated
  palette), a clean window stays UNVERIFIED whatever the verdict says. This withholds
  HEALTHY only and never lowers the score. It does not prove the other frames natural: a
  card with a broad palette passes it (see extend_the_hub.md §8 for what this covers).
"""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from media_ops_video_quality.compare_frames import compare_frames
from media_ops_video_quality.measure_frame import FrameMetrics, measure_frame
from media_ops_video_quality.quality_thresholds import DEFAULT_THRESHOLDS, QualityThresholds


class Status(StrEnum):
    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"
    UNVERIFIED = "UNVERIFIED"


class SampledFrame(BaseModel):
    taken_at: datetime
    jpeg: bytes


class VisionScores(BaseModel):
    """The model's 1-5 rubric for the whole window (filled by the vision pass)."""

    compression_artifacts: int = Field(ge=1, le=5)
    banding: int = Field(ge=1, le=5)
    interlacing_ghosting: int = Field(ge=1, le=5)
    slate_or_bars: int = Field(ge=1, le=5)
    overall: int = Field(ge=1, le=5)
    confidence: float = Field(ge=0, le=1)
    evidence: str


VisionStatus = Literal["ok", "unavailable", "not_requested"]


class FrameAssessment(BaseModel):
    taken_at: datetime
    metrics: FrameMetrics
    black: bool
    flat: bool
    blurred: bool
    blocky: bool
    frozen: bool  # unchanged since the previous frame (and not black or flat)
    graphic: bool  # a few flat colours (card, slate, caption), not black or flat
    scene_change: bool


class WindowAssessment(BaseModel):
    requested_frames: int
    sampled_frames: int
    frames: list[FrameAssessment]
    shares: dict[str, float]  # share of frames per finding: frozen, black, flat, blurred, blocky
    frozen_seconds: float  # longest run of unchanged frames
    graphic_share: float  # share of graphic frames; any at all withholds HEALTHY
    deterministic_score: float
    vision_status: VisionStatus
    vision: VisionScores | None
    score: float
    status: Status
    confidence: float
    basis: str  # what the status rests on, in words


def assess_window(
    frames: list[SampledFrame],
    *,
    requested_frames: int,
    vision: VisionScores | None = None,
    vision_status: VisionStatus = "not_requested",
    thresholds: QualityThresholds = DEFAULT_THRESHOLDS,
) -> WindowAssessment:
    ordered = sorted(frames, key=lambda frame: frame.taken_at)
    assessed = assess_frames(ordered, thresholds)
    shares = {
        finding: (sum(getattr(f, finding) for f in assessed) / len(assessed) if assessed else 0.0)
        for finding in ("frozen", "black", "flat", "blurred", "blocky")
    }
    weights = thresholds.penalty_weights
    deterministic = max(0.0, 100.0 - 100.0 * sum(weights[k].value * v for k, v in shares.items()))
    trusted = (
        vision
        if vision_status == "ok"
        and vision
        and vision.confidence >= thresholds.trusted_vision_confidence.value
        else None
    )
    score = min(deterministic, vision_score(trusted)) if trusted else deterministic
    graphic_share = sum(f.graphic for f in assessed) / len(assessed) if assessed else 0.0
    status, basis = decide_status(
        len(assessed), score, trusted, vision_status, graphic_share, thresholds
    )
    return WindowAssessment(
        requested_frames=requested_frames,
        sampled_frames=len(assessed),
        frames=assessed,
        shares=shares,
        frozen_seconds=longest_frozen_seconds(assessed),
        graphic_share=graphic_share,
        deterministic_score=round(deterministic, 1),
        vision_status=vision_status,
        vision=vision,
        score=round(score, 1),
        status=status,
        confidence=confidence(deterministic, trusted, vision, thresholds),
        basis=basis,
    )


def assess_frames(
    frames: list[SampledFrame], thresholds: QualityThresholds
) -> list[FrameAssessment]:  # noqa: E501
    assessed: list[FrameAssessment] = []
    previous: SampledFrame | None = None
    for frame in frames:
        metrics = measure_frame(frame.jpeg)
        black = (
            metrics.luma_mean < thresholds.black_below_luma_mean.value
            and metrics.luma_stddev < thresholds.flat_below_luma_stddev.value
        )
        flat = not black and metrics.luma_stddev < thresholds.flat_below_luma_stddev.value
        change = compare_frames(previous.jpeg, frame.jpeg).mean_abs_difference if previous else None  # noqa: E501
        assessed.append(
            FrameAssessment(
                taken_at=frame.taken_at,
                metrics=metrics,
                black=black,
                flat=flat,
                blurred=not (black or flat)
                and metrics.sharpness < thresholds.blurred_below_sharpness.value,  # noqa: E501
                blocky=not (black or flat)
                and metrics.blockiness_estimate > thresholds.blocky_above_excess.value,  # noqa: E501
                frozen=change is not None
                and not (black or flat)
                and change < thresholds.frozen_below_difference.value,  # noqa: E501
                graphic=not (black or flat)
                and metrics.palette_concentration
                > thresholds.graphic_above_palette_concentration.value,  # noqa: E501
                scene_change=change is not None
                and change > thresholds.scene_change_above_difference.value,  # noqa: E501
            )
        )
        previous = frame
    return assessed


def longest_frozen_seconds(frames: list[FrameAssessment]) -> float:
    longest, run_start = 0.0, None
    for previous, frame in zip(frames, frames[1:], strict=False):
        if frame.frozen:
            run_start = run_start or previous.taken_at
            longest = max(longest, (frame.taken_at - run_start).total_seconds())
        else:
            run_start = None
    return longest


def vision_score(vision: VisionScores) -> float:
    return (min(max(vision.overall, 1), 5) - 1) / 4 * 100


def status_for(score: float, thresholds: QualityThresholds) -> Status:
    for name in ("HEALTHY", "WARNING", "DEGRADED"):
        if score >= thresholds.status_floors[name].value:
            return Status(name)
    return Status.CRITICAL


def decide_status(
    sampled: int,
    score: float,
    trusted: VisionScores | None,
    vision_status: VisionStatus,
    graphic_share: float,
    thresholds: QualityThresholds,
) -> tuple[Status, str]:
    if sampled < 2:
        return Status.UNVERIFIED, "fewer than 2 distinct frames: freeze and change are unknown"
    status = status_for(score, thresholds)
    # Any graphic frame: the one rubric call saw it, so its text may have steered the verdict.
    if trusted and status is Status.HEALTHY and graphic_share > 0:
        return Status.UNVERIFIED, (
            "a frame is a graphic (card, slate or caption screen) and the vision verdict "
            "saw it: its text may have steered the verdict, so it doesn't make it healthy"
        )
    if trusted:
        return status, "deterministic measurements and the vision rubric"
    if status is Status.HEALTHY:
        return Status.UNVERIFIED, f"deterministic measurements only (vision {vision_status})"
    return status, f"deterministic measurements only (vision {vision_status})"


def confidence(
    deterministic: float,
    trusted: VisionScores | None,
    vision: VisionScores | None,
    thresholds: QualityThresholds,
) -> float:
    """0.5 on the measurements alone. A trusted vision verdict that agrees raises it and one
    that disagrees lowers it. An untrusted verdict can only lower it, never raise it."""
    t = thresholds
    if vision is None:
        return t.single_signal_confidence.value
    agree = status_for(deterministic, t) == status_for(vision_score(vision), t)
    if trusted is None:
        return t.single_signal_confidence.value if agree else t.untrusted_disagree_confidence.value
    if agree:
        return round(min(1.0, trusted.confidence + t.vision_agree_step.value), 2)
    return round(max(0.0, trusted.confidence - t.vision_disagree_step.value), 2)
