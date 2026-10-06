"""Media-level defects from probed segments (spec §10)."""

from hls_doctor.adapters.ffprobe.probe_report import SegmentProbe
from hls_doctor.domain.correlate.finding_model import Finding, create_finding, observe
from hls_doctor.domain.correlate.severity_model import Confidence, Severity
from hls_doctor.domain.media.analyze_timestamps import analyze_timestamps


def detect_media_defects(
    probes: list[SegmentProbe], *, discontinuity_present: bool = True
) -> list[Finding]:
    findings: list[Finding] = []
    for probe in probes:
        check_timestamp_regression(probe, findings)
    check_codec_change(probes, findings, discontinuity_present=discontinuity_present)
    return findings


def check_timestamp_regression(probe: SegmentProbe, findings: list[Finding]) -> None:
    analysis = analyze_timestamps(probe)
    if analysis.regressions:
        shown = "; ".join(analysis.regressions[:3])
        findings.append(
            create_finding(
                "Video timestamps go backwards inside a segment",
                Severity.ERROR,
                Confidence.CONFIRMED,
                "media-timeline",
                [probe.url],
                [
                    observe(
                        f"{len(analysis.regressions)} PTS regression(s) across"
                        f" {analysis.packet_count} probed packets: {shown}"
                    )
                ],
                "Presentation timestamps must be monotonic within a segment.",
                "Decoders drop or re-order frames; players may stall or glitch.",
                likely_causes=["encoder timestamp wrap", "bad splice or re-mux"],
                next_probe="Probe the neighbouring segments to see where monotonicity breaks.",
            )  # fmt: skip
        )


def check_codec_change(
    probes: list[SegmentProbe], findings: list[Finding], *, discontinuity_present: bool
) -> None:
    """A codec/resolution change between probed segments of one rendition."""
    described: list[tuple[str, str]] = []
    for probe in probes:
        for stream in probe.streams:
            if stream.codec_type == "video" and stream.codec_name:
                described.append((probe.url, f"{stream.codec_name}/{stream.width}x{stream.height}"))
    distinct = {description for _, description in described}
    if len(distinct) <= 1:
        return
    if discontinuity_present:
        findings.append(
            create_finding(
                "Video configuration changes between probed segments",
                Severity.WARNING,
                Confidence.MEDIUM,
                "media-timeline",
                sorted({url for url, _ in described}),
                [observe(f"Probed configurations: {', '.join(sorted(distinct))}")],
                "Segments of one rendition present different codec configurations.",
                "A discontinuity is declared; conforming players reset their decoders.",
            )  # fmt: skip
        )
        return
    findings.append(
        create_finding(
            "Codec change without a signaled discontinuity",
            Severity.ERROR,
            Confidence.HIGH,
            "media-timeline",
            sorted({url for url, _ in described}),
            [
                observe(
                    f"Probed configurations differ ({', '.join(sorted(distinct))}) and the"
                    " playlist declares no EXT-X-DISCONTINUITY between them"
                )
            ],
            "A media configuration change must be announced with a discontinuity.",
            "Players keep the old decoder configuration and fail or glitch at the change.",
            likely_causes=["ad splice without discontinuity", "encoder profile change"],
            next_probe="Probe the segments between the two configurations to find the switch.",
        )  # fmt: skip
    )
