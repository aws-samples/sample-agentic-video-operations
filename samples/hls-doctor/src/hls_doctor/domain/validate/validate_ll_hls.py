"""Low-Latency HLS structural checks (spec §15)."""

from hls_doctor.domain.correlate.finding_model import Finding, create_finding, observe
from hls_doctor.domain.correlate.severity_model import Confidence, Severity
from hls_doctor.domain.playlist.media_playlist_model import MediaPlaylist

MIN_HOLD_BACK_TARGETS = 3
MIN_PART_HOLD_BACK_FACTOR = 2.0


def is_low_latency(media: MediaPlaylist) -> bool:
    return media.part_target is not None or any(segment.parts for segment in media.segments)


def validate_ll_hls(url: str, media: MediaPlaylist) -> list[Finding]:
    if not is_low_latency(media):
        return []
    findings: list[Finding] = []
    check_server_control(url, media, findings)
    check_part_durations(url, media, findings)
    return findings


def check_server_control(url: str, media: MediaPlaylist, findings: list[Finding]) -> None:
    control = media.server_control
    if control is None:
        findings.append(
            create_finding(
                "LL-HLS playlist without EXT-X-SERVER-CONTROL",
                Severity.ERROR,
                Confidence.CONFIRMED,
                "ll-hls",
                [url],
                [observe("The playlist carries parts but no EXT-X-SERVER-CONTROL tag")],
                "Low-latency clients need the server's blocking-reload contract.",
                "Clients fall back to full-latency behavior or fail to tune in.",
                standards_reference="Apple LL-HLS, EXT-X-SERVER-CONTROL",
            )  # fmt: skip
        )
        return
    if not control.can_block_reload:
        findings.append(
            create_finding(
                "LL-HLS without CAN-BLOCK-RELOAD=YES",
                Severity.ERROR,
                Confidence.CONFIRMED,
                "ll-hls",
                [url],
                [
                    observe(
                        f"EXT-X-SERVER-CONTROL at line {control.line_number} does not"
                        " declare CAN-BLOCK-RELOAD=YES"
                    )
                ],
                "Blocking playlist reload is the core of low-latency delivery.",
                "Clients poll instead of blocking; latency grows by a target duration.",
            )  # fmt: skip
        )
    part_target = media.part_target or 0
    if (
        control.part_hold_back is not None
        and part_target
        and control.part_hold_back < MIN_PART_HOLD_BACK_FACTOR * part_target
    ):
        findings.append(
            create_finding(
                "PART-HOLD-BACK below two part targets",
                Severity.WARNING,
                Confidence.CONFIRMED,
                "ll-hls",
                [url],
                [
                    observe(
                        f"PART-HOLD-BACK={control.part_hold_back} with PART-TARGET={part_target}"
                    )
                ],
                "Clients positioned closer than two part durations stall on jitter.",
                "Frequent micro-stalls at the live edge.",
                standards_reference="Apple LL-HLS, PART-HOLD-BACK",
            )  # fmt: skip
        )


def check_part_durations(url: str, media: MediaPlaylist, findings: list[Finding]) -> None:
    part_target = media.part_target
    if part_target is None:
        findings.append(
            create_finding(
                "Parts without EXT-X-PART-INF",
                Severity.ERROR,
                Confidence.CONFIRMED,
                "ll-hls",
                [url],
                [observe("EXT-X-PART tags appear but no EXT-X-PART-INF declares PART-TARGET")],
                "The part target duration must be declared before parts are used.",
                "Clients cannot pace part requests.",
            )  # fmt: skip
        )
        return
    limit = part_target + 0.05
    for segment in media.segments:
        for part in segment.parts:
            if part.duration is not None and part.duration > limit:
                findings.append(
                    create_finding(
                        "Part duration exceeds PART-TARGET",
                        Severity.ERROR,
                        Confidence.CONFIRMED,
                        "ll-hls",
                        [url],
                        [
                            observe(
                                f"Part {part.uri!r} at line {part.line_number} lasts"
                                f" {part.duration}s against PART-TARGET={part_target}"
                            )
                        ],
                        "Every partial segment must fit the declared part target.",
                        "Blocking reload timing breaks; clients miss the next part.",
                    )  # fmt: skip
                )
                return
