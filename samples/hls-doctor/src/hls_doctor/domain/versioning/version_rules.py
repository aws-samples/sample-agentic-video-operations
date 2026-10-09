"""Feature-to-minimum-EXT-X-VERSION table (spec §8).

The rows mirror the Protocol Version Compatibility table of
draft-pantos-hls-rfc8216bis §8 exactly: only syntax that section lists
raises a requirement. Notably, EXT-X-DATERANGE and EXT-X-GAP are NOT
version-gated there - flagging them was a review-confirmed false positive
on real ad-inserted streams.
"""

from collections.abc import Callable

from hls_doctor.domain.playlist.media_playlist_model import MediaPlaylist
from hls_doctor.domain.playlist.multivariant_model import MultivariantPlaylist

MediaRule = tuple[int, str, Callable[[MediaPlaylist], bool]]
MultivariantRule = tuple[int, str, Callable[[MultivariantPlaylist], bool]]


def has_fractional_extinf(media: MediaPlaylist) -> bool:
    return any(
        segment.duration is not None and not float(segment.duration).is_integer()
        for segment in media.segments
    )


def keys_of(media: MediaPlaylist) -> list:
    return [segment.key for segment in media.segments if segment.key is not None]


def maps_of(media: MediaPlaylist) -> list:
    return [s.segment_map for s in media.segments if s.segment_map is not None]


MEDIA_RULES: list[MediaRule] = [
    (2, "EXT-X-KEY with IV", lambda m: any(k.iv is not None for k in keys_of(m))),
    (3, "floating-point EXTINF durations", has_fractional_extinf),
    (4, "EXT-X-BYTERANGE", lambda m: any(s.byterange for s in m.segments)),
    (4, "EXT-X-I-FRAMES-ONLY", lambda m: m.iframes_only),
    (5, "EXT-X-KEY METHOD=SAMPLE-AES", lambda m: any(
        k.method == "SAMPLE-AES" for k in keys_of(m))),
    (5, "KEYFORMAT/KEYFORMATVERSIONS", lambda m: any(
        k.keyformat or k.keyformatversions for k in keys_of(m))),
    (5, "EXT-X-MAP in an I-frame playlist", lambda m: m.iframes_only and bool(maps_of(m))),
    (6, "EXT-X-MAP without I-FRAMES-ONLY", lambda m: (not m.iframes_only) and bool(maps_of(m))),
    (9, "EXT-X-SKIP", lambda m: m.skip is not None),
    (10, "EXT-X-SKIP with RECENTLY-REMOVED-DATERANGES", lambda m: (
        m.skip is not None and m.skip.recently_removed_dateranges)),
]  # fmt: skip

MULTIVARIANT_RULES: list[MultivariantRule] = [
    (7, "SERVICEn CLOSED-CAPTIONS INSTREAM-ID", lambda p: any(
        (r.instream_id or "").startswith("SERVICE") for r in p.renditions)),
    (8, "EXT-X-DEFINE variable substitution", lambda p: bool(p.defines)),
    (11, "EXT-X-DEFINE with QUERYPARAM", lambda p: any(
        d.queryparam is not None for d in p.defines)),
    (12, "REQ-VIDEO-LAYOUT attribute", lambda p: any(
        "REQ-VIDEO-LAYOUT" in v.attributes for v in p.variants)),
]  # fmt: skip
