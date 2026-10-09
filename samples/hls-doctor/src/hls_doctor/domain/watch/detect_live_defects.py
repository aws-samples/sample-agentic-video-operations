"""Live-playlist defects visible across a watch window's snapshots (spec §9)."""

from hls_doctor.domain.correlate.finding_model import Finding, create_finding, observe
from hls_doctor.domain.correlate.severity_model import Confidence, Severity
from hls_doctor.domain.watch.playlist_snapshot import PlaylistSnapshot


def detect_live_defects(
    url: str, snapshots: list[PlaylistSnapshot], target_duration: int | None
) -> list[Finding]:
    if len(snapshots) < 2 or snapshots[0].endlist:
        return []
    findings: list[Finding] = []
    check_frozen_playlist(url, snapshots, target_duration, findings)
    check_sequence_regression(url, snapshots, findings)
    check_stale_cdn(url, snapshots, target_duration, findings)
    return findings


def check_frozen_playlist(
    url: str,
    snapshots: list[PlaylistSnapshot],
    target_duration: int | None,
    findings: list[Finding],
) -> None:
    first, last = snapshots[0], snapshots[-1]
    window_ms = last.at_ms - first.at_ms
    expected_advance_ms = (target_duration or 6) * 1000
    if last.newest_msn == first.newest_msn and window_ms >= 2 * expected_advance_ms:
        findings.append(
            create_finding(
                "Frozen live playlist",
                Severity.ERROR,
                Confidence.HIGH,
                "live-playlist",
                [url],
                [
                    observe(
                        f"MSN stayed at {first.newest_msn} across {len(snapshots)} reloads"
                        f" over {window_ms / 1000:.1f} s (expected a new segment about every"
                        f" {expected_advance_ms / 1000:.0f} s)",
                        last.evidence_id,
                    )
                ],
                "The live playlist is not advancing.",
                "Players exhaust their buffer and stall at the live edge.",
                likely_causes=["packager stopped publishing", "stale object pinned upstream"],
                next_probe="Fetch the playlist directly from the origin, bypassing the CDN.",
            )  # fmt: skip
        )


def check_sequence_regression(
    url: str, snapshots: list[PlaylistSnapshot], findings: list[Finding]
) -> None:
    for previous, current in zip(snapshots, snapshots[1:], strict=False):
        if current.media_sequence < previous.media_sequence:
            findings.append(
                create_finding(
                    "MEDIA-SEQUENCE went backwards",
                    Severity.ERROR,
                    Confidence.CONFIRMED,
                    "live-playlist",
                    [url],
                    [
                        observe(
                            f"MEDIA-SEQUENCE dropped from {previous.media_sequence} to"
                            f" {current.media_sequence} between reloads at"
                            f" +{previous.at_ms} ms and +{current.at_ms} ms",
                            current.evidence_id,
                        )
                    ],
                    "Sequence numbers must only increase for one presentation.",
                    "Players treat this as a new timeline; most restart or error.",
                    likely_causes=["failover to an unsynchronized packager", "origin rollback"],
                )  # fmt: skip
            )
            return


def check_stale_cdn(
    url: str,
    snapshots: list[PlaylistSnapshot],
    target_duration: int | None,
    findings: list[Finding],
) -> None:
    expected_seconds = float(target_duration or 6)
    stale = [
        snapshot for snapshot in snapshots
        if snapshot.age_header is not None and is_stale(snapshot.age_header, expected_seconds)
    ]  # fmt: skip
    if len(stale) >= 2:
        worst = max(stale, key=lambda snapshot: float(snapshot.age_header or 0))
        findings.append(
            create_finding(
                "Stale live playlist served from cache",
                Severity.ERROR,
                Confidence.HIGH,
                "delivery",
                [url],
                [
                    observe(
                        f"{len(stale)} of {len(snapshots)} reloads carried Age >"
                        f" {expected_seconds:.0f} s (worst Age: {worst.age_header} s)"
                        + (f" with constant ETag {worst.etag}" if worst.etag else ""),
                        worst.evidence_id,
                    )
                ],
                "The CDN keeps serving a playlist generation older than the target duration.",
                "Live clients fall behind and stall; the live window appears frozen.",
                likely_causes=["cache TTL above the segment duration", "origin shielding issue"],
                next_probe="Compare the origin response with the edge response for this URL.",
            )  # fmt: skip
        )


def is_stale(age_header: str, expected_seconds: float) -> bool:
    try:
        return float(age_header) > expected_seconds
    except ValueError:
        return False
