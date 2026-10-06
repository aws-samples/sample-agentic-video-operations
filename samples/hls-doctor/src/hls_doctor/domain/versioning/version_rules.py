"""Feature-to-minimum-EXT-X-VERSION table (spec §8, Apple compatibility rules).

Only syntax actually present triggers a requirement; a newer HLS feature does
not automatically require the numerically newest version.
"""

from collections.abc import Callable

from hls_doctor.domain.playlist.media_playlist_model import MediaPlaylist
from hls_doctor.domain.playlist.multivariant_model import MultivariantPlaylist

MediaRule = tuple[int, str, Callable[[MediaPlaylist], bool]]
MultivariantRule = tuple[int, str, Callable[[MultivariantPlaylist], bool]]

MEDIA_RULES: list[MediaRule] = [
    (2, "EXT-X-KEY with IV", lambda m: any(
        s.key is not None and s.key.iv is not None for s in m.segments)),
    (4, "EXT-X-BYTERANGE", lambda m: any(s.byterange for s in m.segments)),
    (4, "EXT-X-I-FRAMES-ONLY", lambda m: m.iframes_only),
    (5, "KEYFORMAT/KEYFORMATVERSIONS", lambda m: any(
        s.key is not None and (s.key.keyformat or s.key.keyformatversions)
        for s in m.segments)),
    (5, "EXT-X-MAP in an I-frame playlist", lambda m: m.iframes_only and any(
        s.segment_map for s in m.segments)),
    (6, "EXT-X-MAP without I-FRAMES-ONLY", lambda m: (not m.iframes_only) and any(
        s.segment_map for s in m.segments)),
    (7, "EXT-X-DATERANGE", lambda m: bool(m.dateranges)),
    (8, "EXT-X-GAP", lambda m: any(s.gap for s in m.segments)),
    (9, "EXT-X-SKIP", lambda m: m.skip is not None),
    (10, "EXT-X-SKIP with RECENTLY-REMOVED-DATERANGES", lambda m: False),
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
