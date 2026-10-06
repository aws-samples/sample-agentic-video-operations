"""Encryption signaling checks (spec §17). Key bytes never appear in findings."""

from hls_doctor.domain.correlate.finding_model import Finding, create_finding, observe
from hls_doctor.domain.correlate.severity_model import Confidence, Severity
from hls_doctor.domain.playlist.media_playlist_model import MediaPlaylist

KNOWN_METHODS = ("NONE", "AES-128", "SAMPLE-AES", "SAMPLE-AES-CTR")


def validate_encryption(url: str, media: MediaPlaylist) -> list[Finding]:
    findings: list[Finding] = []
    keys = {segment.key.line_number: segment.key for segment in media.segments if segment.key}
    for key in keys.values():
        if key.method is None or key.method not in KNOWN_METHODS:
            findings.append(
                create_finding(
                    "EXT-X-KEY with unknown METHOD",
                    Severity.WARNING,
                    Confidence.CONFIRMED,
                    "encryption-signaling",
                    [url],
                    [observe(f"METHOD={key.method!r} at line {key.line_number}")],
                    "The encryption method is not one players widely implement.",
                    "Clients without this method cannot decrypt the segments.",
                    standards_reference="RFC 8216 §4.3.2.4",
                )  # fmt: skip
            )
        if key.method not in (None, "NONE") and not key.uri:
            findings.append(
                create_finding(
                    "Encrypted segments without a key URI",
                    Severity.ERROR,
                    Confidence.CONFIRMED,
                    "encryption-signaling",
                    [url],
                    [
                        observe(
                            f"EXT-X-KEY at line {key.line_number} has METHOD={key.method}"
                            " but no URI"
                        )
                    ],
                    "Segments are declared encrypted with no way to fetch the key.",
                    "Playback fails at the first encrypted segment.",
                    standards_reference="RFC 8216 §4.3.2.4",
                )  # fmt: skip
            )
    return findings
