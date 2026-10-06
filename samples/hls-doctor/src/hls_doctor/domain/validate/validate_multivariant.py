"""Multivariant Playlist semantic checks (spec §7)."""

from hls_doctor.domain.correlate.finding_model import Finding, create_finding, observe
from hls_doctor.domain.correlate.severity_model import Confidence, Severity
from hls_doctor.domain.playlist.multivariant_model import MultivariantPlaylist


def validate_multivariant(url: str, playlist: MultivariantPlaylist) -> list[Finding]:
    findings: list[Finding] = []
    check_required_variant_attributes(url, playlist, findings)
    check_group_references(url, playlist, findings)
    check_duplicate_variants(url, playlist, findings)
    return findings


def check_required_variant_attributes(
    url: str, playlist: MultivariantPlaylist, findings: list[Finding]
) -> None:
    missing_bandwidth = [v.line_number for v in playlist.variants if v.bandwidth is None]
    if missing_bandwidth:
        findings.append(
            create_finding(
                "Variant without BANDWIDTH",
                Severity.ERROR,
                Confidence.CONFIRMED,
                "multivariant-structure",
                [url],
                [observe(f"EXT-X-STREAM-INF without BANDWIDTH at lines {missing_bandwidth}")],
                "BANDWIDTH is required on every variant stream.",
                "ABR selection is undefined; players may refuse the variant.",
                standards_reference="RFC 8216 §4.3.4.2",
            )  # fmt: skip
        )
    missing_codecs = [
        v.line_number for v in playlist.variants if not v.codecs and not v.iframe_only
    ]
    if missing_codecs:
        findings.append(
            create_finding(
                "Variant without CODECS",
                Severity.WARNING,
                Confidence.CONFIRMED,
                "multivariant-structure",
                [url],
                [observe(f"Variants without CODECS at lines {missing_codecs}")],
                "CODECS should be declared so players can pre-select decodable variants.",
                "Players probe media to decide; startup is slower and may fail late.",
                standards_reference="HLS Authoring Specification",
            )  # fmt: skip
        )


def check_group_references(
    url: str, playlist: MultivariantPlaylist, findings: list[Finding]
) -> None:
    groups = {
        (rendition.media_type.upper(), rendition.group_id)
        for rendition in playlist.renditions
        if rendition.group_id
    }
    for variant in playlist.variants:
        references = (
            ("AUDIO", variant.audio), ("VIDEO", variant.video),
            ("SUBTITLES", variant.subtitles), ("CLOSED-CAPTIONS", variant.closed_captions),
        )  # fmt: skip
        for media_type, group_id in references:
            if group_id and group_id != "NONE" and (media_type, group_id) not in groups:
                findings.append(
                    create_finding(
                        f"Variant references missing {media_type} group",
                        Severity.ERROR,
                        Confidence.CONFIRMED,
                        "multivariant-structure",
                        [url],
                        [
                            observe(
                                f"Line {variant.line_number} references {media_type} group"
                                f" {group_id!r}, but no EXT-X-MEDIA declares it"
                            )
                        ],
                        "Every group reference must match a rendition group.",
                        "Players fail to start or silently drop the alternate media.",
                        standards_reference="RFC 8216 §4.3.4.2",
                    )  # fmt: skip
                )


def check_duplicate_variants(
    url: str, playlist: MultivariantPlaylist, findings: list[Finding]
) -> None:
    seen: dict[str, int] = {}
    for variant in playlist.variants:
        if variant.uri in seen:
            findings.append(
                create_finding(
                    "Duplicate variant URI",
                    Severity.WARNING,
                    Confidence.CONFIRMED,
                    "multivariant-structure",
                    [url],
                    [
                        observe(
                            f"URI {variant.uri!r} appears at lines {seen[variant.uri]} and"
                            f" {variant.line_number}"
                        )
                    ],
                    "Two variant entries point at the same media playlist.",
                    "ABR ladders with duplicates confuse selection logic.",
                )  # fmt: skip
            )
        seen.setdefault(variant.uri, variant.line_number)
