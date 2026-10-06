"""General playlist syntax checks that apply to every playlist (spec §7)."""

from hls_doctor.domain.correlate.finding_model import Finding, Observation
from hls_doctor.domain.correlate.severity_model import Confidence, Severity
from hls_doctor.domain.playlist.playlist_line import PlaylistLine
from hls_doctor.domain.report.quote_untrusted import quote_untrusted

UNIQUE_TAGS = (
    "EXT-X-VERSION", "EXT-X-TARGETDURATION", "EXT-X-MEDIA-SEQUENCE",
    "EXT-X-DISCONTINUITY-SEQUENCE", "EXT-X-PLAYLIST-TYPE", "EXT-X-I-FRAMES-ONLY",
    "EXT-X-INDEPENDENT-SEGMENTS",
)  # fmt: skip


def validate_syntax(url: str, lines: list[PlaylistLine]) -> list[Finding]:
    findings: list[Finding] = []
    check_extm3u(url, lines, findings)
    check_duplicate_tags(url, lines, findings)
    surface_unknown_tags(url, lines, findings)
    return findings


def check_extm3u(url: str, lines: list[PlaylistLine], findings: list[Finding]) -> None:
    first_content = next((line for line in lines if line.kind != "blank"), None)
    if first_content is None or first_content.name != "EXTM3U":
        findings.append(
            Finding(
                finding_id="",
                title="Playlist does not start with #EXTM3U",
                severity=Severity.FATAL,
                confidence=Confidence.CONFIRMED,
                category="playlist-syntax",
                affected_resources=[url],
                observations=[
                    Observation(
                        statement="First non-blank line is "
                        f"{quote_untrusted(first_content.raw, 60)!r}"
                        if first_content
                        else "The playlist body is empty"
                    )
                ],
                interpretation="The response is not a valid M3U8 playlist.",
                playback_impact="Players reject the playlist outright.",
                likely_causes=["HTML error body served as playlist", "wrong URL"],
                standards_reference="RFC 8216 §4.3.1.1",
            )
        )


def check_duplicate_tags(url: str, lines: list[PlaylistLine], findings: list[Finding]) -> None:
    for tag in UNIQUE_TAGS:
        occurrences = [line.number for line in lines if line.name == tag]
        if len(occurrences) > 1:
            findings.append(
                Finding(
                    finding_id="",
                    title=f"Duplicate {tag} tag",
                    severity=Severity.ERROR,
                    confidence=Confidence.CONFIRMED,
                    category="playlist-syntax",
                    affected_resources=[url],
                    observations=[Observation(statement=f"{tag} appears on lines {occurrences}")],
                    interpretation=f"{tag} must appear at most once per playlist.",
                    playback_impact="Player behavior is undefined; some ignore the playlist.",
                    standards_reference="RFC 8216 §4.3",
                )
            )


def surface_unknown_tags(url: str, lines: list[PlaylistLine], findings: list[Finding]) -> None:
    unknown = [line for line in lines if line.kind == "tag" and not line.is_known_tag]
    if unknown:
        shown = ", ".join(f"{line.name} (line {line.number})" for line in unknown[:5])
        findings.append(
            Finding(
                finding_id="",
                title=f"{len(unknown)} tag(s) not interpreted by this inspector",
                severity=Severity.INFO,
                confidence=Confidence.CONFIRMED,
                category="playlist-inventory",
                affected_resources=[url],
                observations=[Observation(statement=f"Uninterpreted tags: {shown}")],
                interpretation="These tags are preserved and surfaced, not validated.",
                playback_impact="None established; vendor or newer-than-supported syntax.",
            )
        )
