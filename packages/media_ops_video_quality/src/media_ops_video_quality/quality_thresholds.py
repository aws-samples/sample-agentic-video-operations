"""Every threshold the visual quality assessment uses, as data with its rationale.

Calibrated on the synthetic sequences of scripts/generate_quality_fixtures.py (a moving test
pattern at 640x360 and 320x180) by sweeping JPEG quality and blur radius; the measured ranges
are quoted per threshold. Real thumbnails differ, so a read-only run against a sandbox
channel re-checks these before release. Override a value by passing other thresholds.
"""

from pydantic import BaseModel, Field


class Threshold(BaseModel, frozen=True):
    value: float
    rationale: str


class QualityThresholds(BaseModel, frozen=True):
    blurred_below_sharpness: Threshold = Threshold(
        value=600.0,
        rationale=(
            "Laplacian variance at 320 px. Sharp pattern 2377-2864; Gaussian blur r1 1479, "
            "r1.5 275, r2 146, r4 124. 600 is the log midpoint of r1 and r1.5. Judged only on "
            "frames with content (not flat), because a flat scene has no detail to lose."
        ),
    )
    blocky_above_excess: Threshold = Threshold(
        value=1.0,
        rationale=(
            "Extra luma step at 8-px boundaries, in levels. JPEG q45-q95 and any blur <= 0.54; "
            "black and slate 0.00; q30 ~1.0; q15 1.9-2.2; q5 1.75-3.2. 1.0 marks visible "
            "blocking. An estimate: the thumbnail's own JPEG grid contributes."
        ),
    )
    black_below_luma_mean: Threshold = Threshold(
        value=20.0,
        rationale="Video black is luma 16 (BT.709); 20 leaves room for noise. Black fixture 16.0.",
    )
    flat_below_luma_stddev: Threshold = Threshold(
        value=6.0,
        rationale=(
            "Luma standard deviation. Programme pattern 60-65; slate 1.2; black 0.04. Below 6 "
            "the frame is a flat field or a plain slate; text or a logo can raise it."
        ),
    )
    frozen_below_difference: Threshold = Threshold(
        value=0.4,
        rationale=(
            "Mean absolute luma change between consecutive frames at 320 px. Identical frames "
            "0.000; the same picture re-encoded q90 vs q85 0.29 (q60 0.99); slowest moving "
            "fixture 0.66. A freeze re-encoded at a much lower quality can read higher: the "
            "MQCS freeze signal cross-checks it."
        ),
    )
    graphic_above_palette_concentration: Threshold = Threshold(
        value=0.45,
        rationale=(
            "Share of pixels in the three most populated 8-level luma bins, at 320 px. "
            "Programme pattern, blurred and q5 at 640x360 and 320x180 q75: 0.27-0.34; a "
            "scrolling full-frame text card 0.53-0.67; slate and black 1.00. 0.45 sits between. "
            "A frame above it is a graphic (card, slate, caption): not a defect, but any "
            "one withholds HEALTHY from a vision verdict that saw it. Uniform real scenes (a "
            "pitch, a plain backdrop) and full-frame sponsor slates also exceed it and stay "
            "UNVERIFIED: that fails toward doubt. A card with a broad palette stays under "
            "it: the measurement detects concentrated cards, it never proves programme."
        ),
    )
    scene_change_above_difference: Threshold = Threshold(
        value=30.0,
        rationale="Moving fixtures change at most 2.95; cuts to slate or black measure 56-81.",
    )
    penalty_weights: dict[str, Threshold] = Field(
        default_factory=lambda: {
            name: Threshold(value=weight, rationale=reason)
            for name, (weight, reason) in {
                "frozen": (0.8, STOP_REASON),
                "black": (0.8, STOP_REASON),
                "flat": (0.8, STOP_REASON),
                "blurred": (0.4, DEGRADE_REASON),
                "blocky": (0.4, DEGRADE_REASON),
            }.items()
        }  # fmt: skip
    )
    status_floors: dict[str, Threshold] = Field(
        default_factory=lambda: {
            "HEALTHY": Threshold(
                value=85.0,
                rationale=(
                    "Design choice set against the weights: a window stays HEALTHY while "
                    "under ~19% of it is frozen, black or flat (0.8 each) or under ~37% "
                    "blurred or blocky (0.4). The clean fixture scores 100."
                ),
            ),
            "WARNING": Threshold(
                value=65.0,
                rationale=(
                    "Design choice: up to ~44% stop-class or ~87% degrade-class frames is a "
                    "warning, so a short glitch inside a window is visible but not alarming."
                ),
            ),
            "DEGRADED": Threshold(
                value=40.0,
                rationale=(
                    "Measured on the fixtures: a fully blurred or blocky window scores 60 "
                    "(DEGRADED), fully frozen 28 and black or slate 20 (CRITICAL). Between "
                    "those, 40 keeps a picture that is soft but present out of CRITICAL."
                ),
            ),
        }
    )
    trusted_vision_confidence: Threshold = Threshold(
        value=0.5,
        rationale=(
            "Design choice: below even odds on the model's own stated confidence, its "
            "verdict is reported but neither scored nor allowed to raise confidence."
        ),
    )
    single_signal_confidence: Threshold = Threshold(
        value=0.5,
        rationale=(
            "Design choice: one source (the measurements alone, or an untrusted verdict that "
            "agrees) says what the frames show but nothing confirms it: even odds."
        ),
    )
    vision_agree_step: Threshold = Threshold(
        value=0.2,
        rationale=(
            "Design choice: a trusted verdict on the same frames that agrees adds 0.2 to its "
            "own confidence, so a 0.8 verdict plus agreeing measurements reaches 1.0."
        ),
    )
    vision_disagree_step: Threshold = Threshold(
        value=0.3,
        rationale=(
            "Design choice: larger than the agree step, because a contradiction is stronger "
            "evidence of a wrong reading than agreement is of a right one (fail toward doubt)."
        ),
    )
    untrusted_disagree_confidence: Threshold = Threshold(
        value=0.2,
        rationale=(
            "Design choice: an untrusted verdict that disagrees can only lower confidence, "
            "from the single-signal 0.5 to 0.2; it never raises it."
        ),
    )
    telemetry_agree_step: Threshold = Threshold(
        value=0.15,
        rationale=(
            "Design choice: an encoder signal (MQCS, fill, input loss) is independent of the "
            "thumbnails but is per-minute over 15 minutes, not the sampled 20-30 s, so it "
            "weighs less than vision of the same frames (0.2). Two agreeing signals take a "
            "single-signal 0.5 to 0.8."
        ),
    )
    telemetry_disagree_step: Threshold = Threshold(
        value=0.25,
        rationale=(
            "Design choice: larger than the agree step for the same fail-toward-doubt reason "
            "as vision; one contradiction takes a single-signal 0.5 to 0.25."
        ),
    )
    finding_majority_share: Threshold = Threshold(
        value=0.5,
        rationale=(
            "Design choice: a picture finding (frozen, black, slate, soft, blocky) needs at "
            "least half the sampled window, so one odd frame doesn't name the incident."
        ),
    )


STOP_REASON = (
    "Frozen, black and flat (slate) pictures mean the service has stopped for viewers: a "
    "fully affected window must score below the DEGRADED floor (100 - 80 = 20 < 40)."
)
DEGRADE_REASON = (
    "Blur and blocking degrade a picture that is still present: a fully affected window "
    "scores 60, DEGRADED but not CRITICAL."
)


DEFAULT_THRESHOLDS = QualityThresholds()
