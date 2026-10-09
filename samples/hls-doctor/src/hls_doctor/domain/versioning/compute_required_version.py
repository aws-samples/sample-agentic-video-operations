"""Compare the declared EXT-X-VERSION with what the used syntax requires (spec §8)."""

from hls_doctor.domain.correlate.finding_model import Finding, create_finding, observe
from hls_doctor.domain.correlate.severity_model import Confidence, Severity
from hls_doctor.domain.playlist.media_playlist_model import MediaPlaylist
from hls_doctor.domain.playlist.multivariant_model import MultivariantPlaylist
from hls_doctor.domain.versioning.version_rules import MEDIA_RULES, MULTIVARIANT_RULES


def required_media_version(media: MediaPlaylist) -> tuple[int, list[str]]:
    requirements = [(version, name) for version, name, used in MEDIA_RULES if used(media)]
    minimum = max((version for version, _ in requirements), default=1)
    return minimum, [f"{name} requires v{version}" for version, name in requirements]


def required_multivariant_version(
    playlist: MultivariantPlaylist,
) -> tuple[int, list[str]]:
    requirements = [(version, name) for version, name, used in MULTIVARIANT_RULES if used(playlist)]
    minimum = max((version for version, _ in requirements), default=1)
    return minimum, [f"{name} requires v{version}" for version, name in requirements]


def compute_version_findings(
    url: str,
    declared: int | None,
    required: int,
    reasons: list[str],
) -> list[Finding]:
    if required <= 1 or (declared is not None and declared >= required):
        return []
    declared_text = f"EXT-X-VERSION:{declared}" if declared else "no EXT-X-VERSION tag (v1)"
    return [
        create_finding(
            "Declared HLS version below the features in use",
            Severity.ERROR,
            Confidence.CONFIRMED,
            "version-compatibility",
            [url],
            [
                observe(
                    f"The playlist declares {declared_text} but its syntax needs v{required}:"
                    f" {'; '.join(reasons)}"
                )
            ],
            "The compatibility version must cover every feature the playlist uses.",
            "Strict players reject the playlist; others behave inconsistently.",
            remediation=f"Declare EXT-X-VERSION:{required} or remove the newer syntax.",
            standards_reference="Apple: About the EXT-X-VERSION tag",
        )  # fmt: skip
    ]
