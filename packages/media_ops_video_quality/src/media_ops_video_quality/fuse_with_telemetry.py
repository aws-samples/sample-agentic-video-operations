"""Fuse what the picture shows with what the encoder reports, into findings an operator acts on.

Each telemetry signal is independent of the thumbnails, so it can confirm or contradict a
picture finding:
- an agreeing signal raises confidence; a contradicting one lowers it, and then nothing
  else raises it: one contradiction is not cancelled by an unrelated healthy signal;
- any contradiction caps the fused status at UNVERIFIED until a re-sample settles it, so a
  picture judged healthy never reads HEALTHY while the encoder reports a freeze or black;
- a signal that was not emitted (no datapoints) is neither: it is listed as unknown;
- an UNVERIFIED picture has nothing to confirm: healthy-looking signals are listed as
  informational, never as agreement, and cannot raise confidence.
Input health has three states. Fill frames or input loss *observed* in the metric window
point upstream; both emitted and zero mean the input kept arriving; neither emitted means
unknown, and then no root cause is claimed.
The steps and the majority share are thresholds with their rationale (quality_thresholds).
The pack collects the telemetry; this module only decides (no AWS, no framework).
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from media_ops_video_quality.assess_window import Status, WindowAssessment
from media_ops_video_quality.quality_thresholds import DEFAULT_THRESHOLDS, QualityThresholds

SEVERITY = [Status.HEALTHY, Status.UNVERIFIED, Status.WARNING, Status.DEGRADED, Status.CRITICAL]
InputHealth = Literal["starved", "flowing", "unknown"]


class SignalReading(BaseModel):
    """One independent signal: did the encoder or transport detect it? None = not emitted."""

    name: str
    detected: bool | None = None


class EncoderSignals(BaseModel):
    """What the encoder or transport reports for one pipeline or flow, in neutral terms.

    Each pack maps its own metrics here (MediaLive: MQCS and fill/input loss; MediaConnect:
    content-quality breaches and source disconnections), so one set of rules fuses both.
    """

    source_id: str
    window_minutes: int
    freeze: SignalReading
    black: SignalReading
    interrupted: SignalReading  # the input stopped delivering at some point in the window
    interruption_phrase: str  # e.g. "fill frames or input loss"
    no_interruption_phrase: str  # e.g. "no fill frames, no input loss"
    unknown_input_phrase: str  # e.g. "no fill-frame or input-loss data"
    readings: list[tuple[str, float | None]]  # raw values, for the evidence
    resource_term: str  # "channel" or "flow"
    picture_location: str  # where the sampled picture is: what a bad picture there implicates
    failover_phrase: str  # what a healthy alternative looks like for this service
    active_input: str | None = None
    # False when the service reports no sender connected at some point in the window (a
    # MediaConnect source's SourceConnected at 0); None where the service has no such signal.
    source_connected: bool | None = None


class PipelineTelemetry(BaseModel):
    """The encoder's own view of one pipeline over a recent window. None = not emitted."""

    pipeline_id: str
    window_minutes: int = 15  # the metric window the values below aggregate
    mqcs_freeze_min: float | None = None  # MqcsFreezeFrameDetected score, 100 = no freeze
    mqcs_black_min: float | None = None  # MqcsBlackFrameDetected score, 100 = no black
    fill_msec_max: float | None = None  # fill frames inserted for a missing input
    input_loss_seconds: float | None = None  # seconds without input packets
    active_input: str | None = None

    def signals(self) -> EncoderSignals:
        """MediaLive's MQCS scores are 100 when clean, lower when detected."""
        emitted = [v for v in (self.fill_msec_max, self.input_loss_seconds) if v is not None]
        return EncoderSignals(
            source_id=self.pipeline_id,
            window_minutes=self.window_minutes,
            freeze=SignalReading(
                name="MqcsFreezeFrameDetected", detected=below_100(self.mqcs_freeze_min)
            ),
            black=SignalReading(
                name="MqcsBlackFrameDetected", detected=below_100(self.mqcs_black_min)
            ),
            interrupted=SignalReading(
                name="FillMsec/InputLossSeconds",
                detected=any(v > 0 for v in emitted) if emitted else None,
            ),
            interruption_phrase="fill frames or input loss",
            no_interruption_phrase="no fill frames, no input loss",
            unknown_input_phrase="no fill-frame or input-loss data",
            resource_term="channel",
            picture_location="in the encoder output",
            failover_phrase="compare pipelines and fail viewers over to a healthy one",
            readings=[
                ("MqcsFreezeFrameDetected min", self.mqcs_freeze_min),
                ("MqcsBlackFrameDetected min", self.mqcs_black_min),
                ("FillMsec max", self.fill_msec_max),
                ("InputLossSeconds", self.input_loss_seconds),
            ],
            active_input=self.active_input,
        )


def below_100(score: float | None) -> bool | None:
    return None if score is None else score < 100


class Finding(StrEnum):
    FROZEN = "frozen"
    BLACK = "black"
    SLATE = "slate_or_flat"
    SOFT = "soft"
    BLOCKY = "blocky"
    PICTURE_PROBLEM = "picture_problem"  # judged degraded, but no single majority defect
    NO_PICTURE_PROBLEM = "no_picture_problem"
    UNVERIFIED = "unverified"  # not enough evidence to judge the picture


class QualityFinding(BaseModel):
    pipeline_id: str
    finding: Finding
    status: Status  # fused: the picture status, capped at UNVERIFIED by any contradiction
    picture_status: Status  # the window assessment alone, before telemetry
    confidence: float = Field(ge=0, le=1)
    agreeing: list[str]
    disagreeing: list[str]
    unknown: list[str]
    informational: list[str]  # healthy-looking signals that cannot confirm an unjudged picture
    evidence: list[str]
    next_action: str


def fuse_with_telemetry(
    pipeline_id: str,
    assessment: WindowAssessment,
    telemetry: PipelineTelemetry | EncoderSignals,
    thresholds: QualityThresholds = DEFAULT_THRESHOLDS,
) -> QualityFinding:
    signals = telemetry.signals() if isinstance(telemetry, PipelineTelemetry) else telemetry
    finding = picture_finding(assessment, thresholds)
    checks = signal_checks(finding, signals)
    agreeing = [name for name, verdict in checks.items() if verdict is True]
    disagreeing = [name for name, verdict in checks.items() if verdict is False]
    unknown = [name for name, verdict in checks.items() if verdict is None]
    informational: list[str] = []
    if finding is Finding.UNVERIFIED:
        agreeing, informational = [], agreeing
    raised = 0 if disagreeing else len(agreeing)
    confidence = (
        assessment.confidence
        + thresholds.telemetry_agree_step.value * raised
        - thresholds.telemetry_disagree_step.value * len(disagreeing)
    )
    status = assessment.status
    if disagreeing:
        status = max(status, Status.UNVERIFIED, key=SEVERITY.index)
    return QualityFinding(
        pipeline_id=pipeline_id,
        finding=finding,
        status=status,
        picture_status=assessment.status,
        confidence=round(min(1.0, max(0.0, confidence)), 2),
        agreeing=agreeing,
        disagreeing=disagreeing,
        unknown=unknown,
        informational=informational,
        evidence=evidence(assessment, signals),
        next_action=next_action(finding, assessment, signals, disagreeing, thresholds),
    )


def picture_finding(
    assessment: WindowAssessment, thresholds: QualityThresholds = DEFAULT_THRESHOLDS
) -> Finding:
    if assessment.sampled_frames < 2:
        return Finding.UNVERIFIED
    for finding, share in (
        (Finding.BLACK, "black"), (Finding.SLATE, "flat"), (Finding.FROZEN, "frozen"),
        (Finding.SOFT, "blurred"), (Finding.BLOCKY, "blocky"),
    ):  # fmt: skip
        if assessment.shares[share] >= thresholds.finding_majority_share.value:
            return finding
    if assessment.status is Status.HEALTHY:
        return Finding.NO_PICTURE_PROBLEM
    if assessment.status is Status.UNVERIFIED:
        return Finding.UNVERIFIED
    # WARNING or worse with no majority defect: trusted vision, or several defects together.
    return Finding.PICTURE_PROBLEM


def input_health(s: EncoderSignals) -> InputHealth:
    if s.interrupted.detected is None:
        return "unknown"
    return "starved" if s.interrupted.detected else "flowing"


def signal_checks(finding: Finding, s: EncoderSignals) -> dict[str, bool | None]:
    """name -> True (agrees with the finding), False (contradicts it), None (not emitted)."""
    freeze, black, starved = s.freeze.detected, s.black.detected, s.interrupted.detected
    if finding is Finding.FROZEN:
        return {s.freeze.name: freeze}
    if finding is Finding.BLACK:
        return {s.black.name: black}
    if finding is Finding.SLATE:
        return {s.interrupted.name: starved}
    if finding in (Finding.NO_PICTURE_PROBLEM, Finding.UNVERIFIED):
        # The encoder reporting a problem the sampled picture does not show is a contradiction.
        return {
            s.freeze.name: None if freeze is None else not freeze,
            s.black.name: None if black is None else not black,
        }
    return {}  # soft, blocky and other picture problems have no encoder counterpart here


def evidence(a: WindowAssessment, s: EncoderSignals) -> list[str]:
    lines = [
        f"{a.sampled_frames} of {a.requested_frames} frames sampled; "
        + (f"score {a.score} ({a.basis})" if a.score is not None else f"no score ({a.basis})")
    ]
    if a.frozen_seconds:
        lines.append(f"picture unchanged for {a.frozen_seconds:g} s")
    if a.vision is not None:
        v = a.vision
        lines.append(
            f"vision ({a.vision_status}, confidence {v.confidence:g}): overall {v.overall}/5, "
            f"compression {v.compression_artifacts}, banding {v.banding}, "
            f"interlacing {v.interlacing_ghosting}, slate {v.slate_or_bars}: {v.evidence}"
        )
    for name, value in s.readings:
        shown = "not emitted" if value is None else f"{value:g}"
        lines.append(f"{name} (last {s.window_minutes} min): {shown}")
    if s.active_input:
        lines.append(f"active input: {s.active_input}")
    return lines


def next_action(
    finding: Finding,
    a: WindowAssessment,
    s: EncoderSignals,
    disagreeing: list[str],
    thresholds: QualityThresholds,
) -> str:
    source = f"input {s.active_input}" if s.active_input else "the active input"
    window = f"the last {s.window_minutes} minutes"
    if disagreeing:
        return (
            f"Signals disagree ({', '.join(disagreeing)} contradicts the picture): re-sample, "
            "then compare the thumbnail with the encoder metrics before acting."
        )
    if finding in (Finding.FROZEN, Finding.BLACK, Finding.SLATE):
        health = input_health(s)
        if health == "starved":
            return (
                f"{s.interruption_phrase[0].upper()}{s.interruption_phrase[1:]} were observed "
                f"on {source} within {window}: check the source and its input, or switch "
                "inputs, then re-sample the picture."
            )
        if health == "flowing":
            return (
                f"{source[0].upper()}{source[1:]} kept arriving over {window} "
                f"({s.no_interruption_phrase}) while the picture is bad "
                f"{s.picture_location}: {s.failover_phrase}."
            )
        return (
            f"Input health is unknown ({s.unknown_input_phrase}): check the input before "
            "deciding between an upstream fault and the output."
        )
    if finding in (Finding.SOFT, Finding.BLOCKY):
        return f"Check the bitrate and encoder settings, and whether {source} itself is degraded."
    if finding is Finding.PICTURE_PROBLEM:
        trusted = (
            a.vision is not None
            and a.vision.confidence >= thresholds.trusted_vision_confidence.value
        )
        basis = "the vision check found it" if trusted else "several measurements are degraded"
        return (
            f"The picture is degraded ({basis}; see the evidence): {s.failover_phrase}, and "
            f"check whether {source} itself is degraded."
        )
    if finding is Finding.UNVERIFIED:
        if a.sampled_frames < 2 and s.source_connected is False:
            # No sender explains the missing picture; enabling thumbnails would not.
            return (
                f"No sender was connected to the source within {window} (SourceConnected "
                "fell to 0): check the sender and the source's ingest settings, then re-run "
                "to judge the picture."
            )
        if a.sampled_frames < 2:
            return (
                f"Enable thumbnails (or start the {s.resource_term}), then re-run to judge "
                "the picture."
            )
        return (
            "Configure THUMBNAIL_MODEL_ID for a vision verdict, then re-run to judge the picture."
        )
    return "No action needed for the picture."
