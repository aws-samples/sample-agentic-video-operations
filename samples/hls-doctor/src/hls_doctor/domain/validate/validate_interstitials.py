"""HLS Interstitial date-range validation: structure only, no fetching (spec §12)."""

from hls_doctor.domain.correlate.finding_model import Finding, create_finding, observe
from hls_doctor.domain.correlate.severity_model import Confidence, Severity
from hls_doctor.domain.playlist.media_playlist_model import DateRangeTag, MediaPlaylist

INTERSTITIAL_CLASS = "com.apple.hls.interstitial"
PRELOAD_CLASS = "com.apple.hls.preload"


def interstitial_dateranges(media: MediaPlaylist) -> list[DateRangeTag]:
    return [
        daterange for daterange in media.dateranges if daterange.range_class == INTERSTITIAL_CLASS
    ]


def validate_interstitials(url: str, media: MediaPlaylist) -> list[Finding]:
    findings: list[Finding] = []
    for daterange in interstitial_dateranges(media):
        check_required_attributes(url, daterange, findings)
        check_duration_sanity(url, daterange, findings)
    return findings


def check_required_attributes(url: str, daterange: DateRangeTag, findings: list[Finding]) -> None:
    missing = []
    if not daterange.range_id:
        missing.append("ID")
    if not daterange.start_date:
        missing.append("START-DATE")
    has_asset = "X-ASSET-URI" in daterange.attributes or "X-ASSET-LIST" in daterange.attributes
    if not has_asset:
        missing.append("X-ASSET-URI or X-ASSET-LIST")
    if missing:
        findings.append(
            create_finding(
                "Interstitial event is missing required attributes",
                Severity.ERROR,
                Confidence.CONFIRMED,
                "interstitials",
                [url],
                [
                    observe(
                        f"EXT-X-DATERANGE at line {daterange.line_number} lacks"
                        f" {', '.join(missing)}"
                    )
                ],
                "An interstitial must identify itself, its start, and its content.",
                "Clients cannot schedule or load the interstitial.",
                standards_reference="Apple HLS Interstitials specification",
            )  # fmt: skip
        )


def check_duration_sanity(url: str, daterange: DateRangeTag, findings: list[Finding]) -> None:
    declared = daterange.duration
    planned = daterange.planned_duration
    if declared is not None and planned is not None and abs(declared - planned) > 1.0:
        findings.append(
            create_finding(
                "Interstitial DURATION disagrees with PLANNED-DURATION",
                Severity.WARNING,
                Confidence.CONFIRMED,
                "interstitials",
                [url],
                [
                    observe(
                        f"Line {daterange.line_number}: DURATION={declared} but"
                        f" PLANNED-DURATION={planned}"
                    )
                ],
                "A finished event should settle on its actual duration.",
                "Resume timing after the interstitial can be off by the difference.",
            )  # fmt: skip
        )
