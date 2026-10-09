"""Media Playlist semantic checks (spec §7)."""

from hls_doctor.domain.correlate.finding_model import Finding, create_finding, observe
from hls_doctor.domain.correlate.severity_model import Confidence, Severity
from hls_doctor.domain.playlist.media_playlist_model import MediaPlaylist


def validate_media_playlist(url: str, media: MediaPlaylist) -> list[Finding]:
    findings: list[Finding] = []
    check_target_duration(url, media, findings)
    check_missing_extinf(url, media, findings)
    check_vod_endlist(url, media, findings)
    check_program_date_time_monotonic(url, media, findings)
    return findings


def check_target_duration(url: str, media: MediaPlaylist, findings: list[Finding]) -> None:
    if media.target_duration is None:
        if media.segments:
            findings.append(
                create_finding(
                    "Missing EXT-X-TARGETDURATION",
                    Severity.ERROR,
                    Confidence.CONFIRMED,
                    "playlist-structure",
                    [url],
                    [observe("The playlist has segments but no EXT-X-TARGETDURATION tag")],
                    "A Media Playlist must declare its target duration.",
                    "Players cannot compute reload timing; many refuse to play.",
                    standards_reference="RFC 8216 §4.3.3.1",
                )  # fmt: skip
            )
        return
    limit = media.target_duration + 0.5
    offenders = [
        segment for segment in media.segments
        if segment.duration is not None and segment.duration > limit
    ]  # fmt: skip
    if offenders:
        worst = max(offenders, key=lambda segment: segment.duration or 0)
        findings.append(
            create_finding(
                "Segment duration exceeds EXT-X-TARGETDURATION",
                Severity.ERROR,
                Confidence.CONFIRMED,
                "playlist-structure",
                [url],
                [
                    observe(
                        f"{len(offenders)} segment(s) exceed TARGETDURATION"
                        f"={media.target_duration};"
                        f" worst is MSN {worst.media_sequence_number} at {worst.duration}s"
                        f" (line {worst.line_number})"
                    )
                ],
                "EXTINF durations must round to at most the target duration.",
                "Live clients mis-time reloads and can stall near the live edge.",
                remediation="Raise TARGETDURATION or fix the segmenter's output.",
                standards_reference="RFC 8216 §4.3.3.1",
            )  # fmt: skip
        )


def check_missing_extinf(url: str, media: MediaPlaylist, findings: list[Finding]) -> None:
    missing = [segment for segment in media.segments if segment.duration is None]
    if missing:
        findings.append(
            create_finding(
                "Segment without EXTINF duration",
                Severity.ERROR,
                Confidence.CONFIRMED,
                "playlist-structure",
                [url],
                [
                    observe(
                        f"{len(missing)} segment URI(s) lack a preceding EXTINF; first at line"
                        f" {missing[0].line_number}"
                    )
                ],
                "Every segment must be preceded by an EXTINF tag.",
                "Players cannot build a timeline; playback may fail to start.",
                standards_reference="RFC 8216 §4.3.2.1",
            )  # fmt: skip
        )


def check_vod_endlist(url: str, media: MediaPlaylist, findings: list[Finding]) -> None:
    if media.playlist_type == "VOD" and not media.endlist:
        findings.append(
            create_finding(
                "VOD playlist without EXT-X-ENDLIST",
                Severity.WARNING,
                Confidence.CONFIRMED,
                "playlist-structure",
                [url],
                [observe("PLAYLIST-TYPE is VOD but the playlist has no EXT-X-ENDLIST")],
                "A VOD presentation should be explicitly ended.",
                "Players keep reloading a playlist that never changes.",
                standards_reference="RFC 8216 §4.3.3.5",
            )  # fmt: skip
        )


def check_program_date_time_monotonic(
    url: str, media: MediaPlaylist, findings: list[Finding]
) -> None:
    timeline = [
        (segment.media_sequence_number, segment.program_date_time, segment.discontinuity)
        for segment in media.segments
        if segment.program_date_time is not None
    ]
    for (_, previous, _), (msn, current, discontinuity) in zip(
        timeline, timeline[1:], strict=False
    ):
        if (
            previous is not None
            and current is not None
            and current < previous
            and not discontinuity
        ):
            findings.append(
                create_finding(
                    "PROGRAM-DATE-TIME goes backwards",
                    Severity.WARNING,
                    Confidence.HIGH,
                    "playlist-structure",
                    [url],
                    [
                        observe(
                            f"PDT at MSN {msn} ({current}) is earlier than the previous"
                            f" ({previous})"
                            " with no discontinuity between them"
                        )
                    ],
                    "Wall-clock timestamps regress without a signaled discontinuity.",
                    "Timeline mapping, seeking and subtitle sync can break.",
                    standards_reference="RFC 8216 §4.3.2.6",
                )  # fmt: skip
            )
            return
