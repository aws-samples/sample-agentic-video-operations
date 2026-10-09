"""One raw playlist line, preserved verbatim so no syntax is silently discarded."""

from typing import Literal

from pydantic import BaseModel

KNOWN_TAGS = frozenset(
    {
        "EXTM3U", "EXT-X-VERSION", "EXTINF", "EXT-X-BYTERANGE", "EXT-X-DISCONTINUITY",
        "EXT-X-KEY", "EXT-X-MAP", "EXT-X-PROGRAM-DATE-TIME", "EXT-X-GAP", "EXT-X-BITRATE",
        "EXT-X-PART", "EXT-X-TARGETDURATION", "EXT-X-MEDIA-SEQUENCE",
        "EXT-X-DISCONTINUITY-SEQUENCE", "EXT-X-ENDLIST", "EXT-X-PLAYLIST-TYPE",
        "EXT-X-I-FRAMES-ONLY", "EXT-X-PART-INF", "EXT-X-SERVER-CONTROL", "EXT-X-MEDIA",
        "EXT-X-STREAM-INF", "EXT-X-I-FRAME-STREAM-INF", "EXT-X-SESSION-DATA",
        "EXT-X-SESSION-KEY", "EXT-X-CONTENT-STEERING", "EXT-X-INDEPENDENT-SEGMENTS",
        "EXT-X-START", "EXT-X-DEFINE", "EXT-X-DATERANGE", "EXT-X-SKIP",
        "EXT-X-PRELOAD-HINT", "EXT-X-RENDITION-REPORT",
        # Common ad-signaling vendor tags the inspector understands (spec §13).
        "EXT-X-CUE-OUT", "EXT-X-CUE-OUT-CONT", "EXT-X-CUE-IN", "EXT-OATCLS-SCTE35",
        "EXT-X-SPLICEPOINT-SCTE35",
    }
)  # fmt: skip

LineKind = Literal["tag", "uri", "comment", "blank"]


class PlaylistLine(BaseModel):
    """A single line: `raw` is byte-for-byte what the playlist said."""

    number: int
    kind: LineKind
    raw: str
    name: str | None = None
    value: str | None = None

    @property
    def is_known_tag(self) -> bool:
        return self.kind == "tag" and self.name in KNOWN_TAGS
