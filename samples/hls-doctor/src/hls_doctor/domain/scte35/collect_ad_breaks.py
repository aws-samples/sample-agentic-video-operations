"""Collect ad-break signaling from a Media Playlist and check its consistency (§13)."""

from pydantic import BaseModel, Field

from hls_doctor.domain.correlate.finding_model import Finding, create_finding, observe
from hls_doctor.domain.correlate.severity_model import Confidence, Severity
from hls_doctor.domain.playlist.media_playlist_model import MediaPlaylist
from hls_doctor.domain.playlist.parse_attribute_list import parse_attribute_list, parse_decimal
from hls_doctor.domain.playlist.playlist_line import PlaylistLine
from hls_doctor.domain.scte35.decode_splice_info import decode_splice_info
from hls_doctor.domain.scte35.splice_model import SpliceInfoSection
from media_ops_contracts.tool_failure import ToolFailure

DURATION_TOLERANCE_SECONDS = 0.5


class AdBreak(BaseModel):
    start_line: int
    declared_duration: float | None = None
    cue_in_line: int | None = None
    payloads: list[str] = Field(default_factory=list)
    decoded: list[SpliceInfoSection] = Field(default_factory=list)
    decode_errors: list[str] = Field(default_factory=list)


def collect_ad_breaks(lines: list[PlaylistLine], media: MediaPlaylist) -> list[AdBreak]:
    breaks: list[AdBreak] = []
    current: AdBreak | None = None
    for line in lines:
        if line.kind != "tag":
            continue
        if line.name == "EXT-X-CUE-OUT":
            current = AdBreak(start_line=line.number, declared_duration=cue_out_duration(line))
            breaks.append(current)
        elif line.name == "EXT-OATCLS-SCTE35" and line.value:
            target = current or AdBreak(start_line=line.number)
            if target is not current:
                breaks.append(target)
                current = target
            target.payloads.append(line.value.strip())
        elif line.name == "EXT-X-CUE-IN" and current is not None:
            current.cue_in_line = line.number
            current = None
    collect_daterange_breaks(media, breaks)
    decode_break_payloads(breaks)
    return breaks


def cue_out_duration(line: PlaylistLine) -> float | None:
    if line.value is None:
        return None
    attributes = parse_attribute_list(line.value)
    return parse_decimal(attributes.get("DURATION")) or parse_decimal(line.value)


def collect_daterange_breaks(media: MediaPlaylist, breaks: list[AdBreak]) -> None:
    for daterange in media.dateranges:
        payload = daterange.attributes.get("SCTE35-OUT") or daterange.attributes.get("SCTE35-CMD")
        if payload is None:
            continue
        ad_break = AdBreak(
            start_line=daterange.line_number,
            declared_duration=daterange.duration or daterange.planned_duration,
            payloads=[payload],
        )
        if daterange.end_date or daterange.attributes.get("SCTE35-IN"):
            ad_break.cue_in_line = daterange.line_number
        breaks.append(ad_break)


def decode_break_payloads(breaks: list[AdBreak]) -> None:
    for ad_break in breaks:
        for payload in ad_break.payloads:
            try:
                ad_break.decoded.append(decode_splice_info(payload))
            except ToolFailure as failure:
                ad_break.decode_errors.append(failure.message)


def validate_ad_breaks(url: str, breaks: list[AdBreak]) -> list[Finding]:
    findings: list[Finding] = []
    for ad_break in breaks:
        check_unterminated(url, ad_break, findings)
        check_malformed_payloads(url, ad_break, findings)
        check_duration_mismatch(url, ad_break, findings)
    return findings


def check_unterminated(url: str, ad_break: AdBreak, findings: list[Finding]) -> None:
    if ad_break.cue_in_line is None:
        findings.append(
            create_finding(
                "Ad break opened without a matching CUE-IN",
                Severity.WARNING,
                Confidence.HIGH,
                "ad-signaling",
                [url],
                [
                    observe(
                        f"The break starting at line {ad_break.start_line} never returns"
                        " to the program"
                    )
                ],
                "Every cue-out must be closed so clients can rejoin the program.",
                "SSAI stitchers may stay in the break; viewers miss content.",
                next_probe="Watch the live playlist to see whether the CUE-IN arrives late.",
            )  # fmt: skip
        )


def check_malformed_payloads(url: str, ad_break: AdBreak, findings: list[Finding]) -> None:
    for error in ad_break.decode_errors:
        findings.append(
            create_finding(
                "Malformed SCTE-35 payload",
                Severity.WARNING,
                Confidence.CONFIRMED,
                "ad-signaling",
                [url],
                [observe(f"Line {ad_break.start_line}: {error}")],
                "The cue payload does not decode as a splice_info_section.",
                "Downstream ad systems ignore the cue or mis-time the break.",
            )  # fmt: skip
        )


def check_duration_mismatch(url: str, ad_break: AdBreak, findings: list[Finding]) -> None:
    if ad_break.declared_duration is None:
        return
    for section in ad_break.decoded:
        decoded_duration = section.break_duration_seconds
        if decoded_duration is None:
            continue
        difference = abs(decoded_duration - ad_break.declared_duration)
        if difference > DURATION_TOLERANCE_SECONDS:
            findings.append(
                create_finding(
                    "Ad break duration disagrees with its SCTE-35 payload",
                    Severity.WARNING,
                    Confidence.CONFIRMED,
                    "ad-signaling",
                    [url],
                    [
                        observe(
                            f"Line {ad_break.start_line} declares"
                            f" {ad_break.declared_duration:.3f} s"
                            f" but the decoded payload says {decoded_duration:.3f} s"
                            f" (event {describe_event(section)})"
                        )
                    ],
                    "Playlist signaling and the binary cue must agree on the break length.",
                    "Ad stitchers cut back early or late; content is clipped or overlaid.",
                    next_probe="Check which value the packager derives the DATERANGE from.",
                )  # fmt: skip
            )


def describe_event(section: SpliceInfoSection) -> str:
    if section.splice_insert is not None:
        return str(section.splice_insert.event_id)
    if section.segmentation_descriptors:
        return str(section.segmentation_descriptors[0].event_id)
    return section.command_name
