"""Alternate audio, subtitle and caption declaration checks (spec §14)."""

from collections import defaultdict

from hls_doctor.domain.correlate.finding_model import Finding, create_finding, observe
from hls_doctor.domain.correlate.severity_model import Confidence, Severity
from hls_doctor.domain.playlist.multivariant_model import MultivariantPlaylist, Rendition


def validate_renditions(url: str, playlist: MultivariantPlaylist) -> list[Finding]:
    findings: list[Finding] = []
    check_duplicate_defaults(url, playlist.renditions, findings)
    check_caption_instream_ids(url, playlist.renditions, findings)
    check_missing_uri(url, playlist.renditions, findings)
    return findings


def check_duplicate_defaults(
    url: str, renditions: list[Rendition], findings: list[Finding]
) -> None:
    defaults: dict[tuple[str, str | None], list[int]] = defaultdict(list)
    for rendition in renditions:
        if rendition.default:
            defaults[(rendition.media_type.upper(), rendition.group_id)].append(
                rendition.line_number
            )
    for (media_type, group_id), lines in defaults.items():
        if len(lines) > 1:
            findings.append(
                create_finding(
                    f"Multiple DEFAULT=YES renditions in {media_type} group",
                    Severity.ERROR,
                    Confidence.CONFIRMED,
                    "rendition-structure",
                    [url],
                    [observe(f"Group {group_id!r} marks DEFAULT=YES at lines {lines}")],
                    "At most one rendition per group may be the default.",
                    "Players pick arbitrarily; language selection is inconsistent.",
                    standards_reference="RFC 8216 §4.3.4.1",
                )  # fmt: skip
            )


def check_caption_instream_ids(
    url: str, renditions: list[Rendition], findings: list[Finding]
) -> None:
    for rendition in renditions:
        if rendition.media_type.upper() == "CLOSED-CAPTIONS" and not rendition.instream_id:
            findings.append(
                create_finding(
                    "CLOSED-CAPTIONS rendition without INSTREAM-ID",
                    Severity.ERROR,
                    Confidence.CONFIRMED,
                    "rendition-structure",
                    [url],
                    [observe(f"EXT-X-MEDIA at line {rendition.line_number} lacks INSTREAM-ID")],
                    "Caption renditions must say which CC channel they describe.",
                    "Players cannot map the caption track; captions are unavailable.",
                    standards_reference="RFC 8216 §4.3.4.1",
                )  # fmt: skip
            )


def check_missing_uri(url: str, renditions: list[Rendition], findings: list[Finding]) -> None:
    for rendition in renditions:
        media_type = rendition.media_type.upper()
        if media_type == "SUBTITLES" and not rendition.uri:
            findings.append(
                create_finding(
                    "SUBTITLES rendition without URI",
                    Severity.ERROR,
                    Confidence.CONFIRMED,
                    "rendition-structure",
                    [url],
                    [observe(f"EXT-X-MEDIA at line {rendition.line_number} has no URI")],
                    "Subtitle renditions must reference a media playlist.",
                    "The subtitle track cannot be loaded.",
                    standards_reference="RFC 8216 §4.3.4.1",
                )  # fmt: skip
            )
