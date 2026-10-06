"""Cross-rendition alignment findings (spec §11)."""

from hls_doctor.domain.align.match_rendition_positions import RenditionPosition
from hls_doctor.domain.correlate.finding_model import Finding, create_finding, observe
from hls_doctor.domain.correlate.severity_model import Confidence, Severity

DRIFT_TOLERANCE_SECONDS = 1.0
MIN_LAG_SEGMENTS = 2


def compare_renditions(positions: list[RenditionPosition]) -> list[Finding]:
    if len(positions) < 2:
        return []
    findings: list[Finding] = []
    check_rendition_lag(positions, findings)
    check_wall_clock_drift(positions, findings)
    check_daterange_sets(positions, findings)
    return findings


def check_rendition_lag(positions: list[RenditionPosition], findings: list[Finding]) -> None:
    video = [p for p in positions if p.role in ("video", "entry") and p.newest_msn is not None]
    if len(video) < 2:
        return
    newest = max(p.newest_msn or 0 for p in video)
    target = max(p.target_duration or 6 for p in video)
    for position in video:
        lag_segments = newest - (position.newest_msn or 0)
        if lag_segments >= MIN_LAG_SEGMENTS:
            findings.append(
                create_finding(
                    "One variant lags its peers at the live edge",
                    Severity.WARNING,
                    Confidence.HIGH,
                    "rendition-alignment",
                    [position.url],
                    [
                        observe(
                            f"Newest MSN is {position.newest_msn} while a peer is at {newest}"
                            f" ({lag_segments} segment(s), about {lag_segments * target} s, behind)"
                        )
                    ],
                    "All variants of one presentation should publish in step.",
                    "ABR switches onto this variant jump backwards or stall.",
                    likely_causes=["one encoder output is behind", "per-variant origin delay"],
                    next_probe="Watch this variant and a peer to measure the publication gap.",
                )  # fmt: skip
            )


def check_wall_clock_drift(positions: list[RenditionPosition], findings: list[Finding]) -> None:
    video = next((p for p in positions if p.role in ("video", "entry") and p.pdt_by_msn), None)
    if video is None:
        return
    for position in positions:
        if position.url == video.url or not position.pdt_by_msn:
            continue
        shared = sorted(set(video.pdt_by_msn) & set(position.pdt_by_msn))
        if not shared:
            continue
        msn = shared[-1]
        drift = (position.pdt_by_msn[msn] - video.pdt_by_msn[msn]).total_seconds()
        if abs(drift) > DRIFT_TOLERANCE_SECONDS:
            direction = "behind" if drift < 0 else "ahead of"
            findings.append(
                create_finding(
                    f"{position.role.capitalize()} rendition drifts from video",
                    Severity.WARNING,
                    Confidence.HIGH,
                    "rendition-alignment",
                    [position.url],
                    [
                        observe(
                            f"At MSN {msn} the {position.role} PROGRAM-DATE-TIME is"
                            f" {abs(drift):.1f} s {direction} the video rendition"
                        )
                    ],
                    "Renditions of one presentation must share the program timeline.",
                    "Lip-sync or subtitle timing is off by the drift amount.",
                    next_probe="Probe the media timestamps of both renditions at this MSN.",
                )  # fmt: skip
            )


def check_daterange_sets(positions: list[RenditionPosition], findings: list[Finding]) -> None:
    # Event consistency applies to the main media timeline: video variants and
    # alternate audio. I-frame and subtitle playlists legitimately omit events.
    positions = [p for p in positions if p.role in ("video", "audio", "entry")]
    tagged = [p for p in positions if p.daterange_ids]
    if not tagged or all(not p.pdt_by_msn and not p.daterange_ids for p in positions):
        return
    reference = tagged[0]
    for position in positions:
        if position.url == reference.url:
            continue
        missing = set(reference.daterange_ids) - set(position.daterange_ids)
        if missing:
            findings.append(
                create_finding(
                    "Date-range events are missing from a rendition",
                    Severity.ERROR,
                    Confidence.CONFIRMED,
                    "rendition-alignment",
                    [position.url],
                    [
                        observe(
                            f"Event id(s) {sorted(missing)} appear in {reference.url}"
                            f" but not in this rendition"
                        )
                    ],
                    "Interstitial and ad events must be signaled consistently everywhere.",
                    "Clients on this rendition miss the event or desynchronize at it.",
                    next_probe="Check the packager's per-rendition manifest generation.",
                )  # fmt: skip
            )
