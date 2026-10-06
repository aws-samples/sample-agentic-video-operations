"""Build the typed Media Playlist model from tokenized lines."""

from hls_doctor.domain.playlist.media_playlist_model import (
    DateRangeTag,
    KeyTag,
    MapTag,
    MediaPlaylist,
    MediaSegment,
    PartTag,
    PreloadHintTag,
    RenditionReportTag,
    ServerControlTag,
    SkipTag,
)
from hls_doctor.domain.playlist.parse_attribute_list import (
    parse_attribute_list,
    parse_decimal,
    parse_integer,
)
from hls_doctor.domain.playlist.parse_multivariant import parse_key_tag
from hls_doctor.domain.playlist.playlist_line import PlaylistLine

AD_CUE_TAGS = frozenset(
    {"EXT-X-CUE-OUT", "EXT-X-CUE-OUT-CONT", "EXT-X-CUE-IN", "EXT-OATCLS-SCTE35",
     "EXT-X-SPLICEPOINT-SCTE35"}
)  # fmt: skip


class ParserState:
    """Accumulates per-segment tags; KEY and MAP persist until replaced (RFC 8216)."""

    def __init__(self) -> None:
        self.active_key: KeyTag | None = None
        self.active_map: MapTag | None = None
        self.start_next_segment()

    def start_next_segment(self) -> None:
        self.duration: float | None = None
        self.title: str | None = None
        self.byterange: str | None = None
        self.discontinuity = False
        self.gap = False
        self.program_date_time: str | None = None
        self.bitrate: int | None = None
        self.parts: list[PartTag] = []
        self.cue_lines: list[int] = []


def parse_media_playlist(lines: list[PlaylistLine]) -> MediaPlaylist:
    playlist = MediaPlaylist()
    state = ParserState()
    for line in lines:
        if line.kind == "uri":
            append_segment(playlist, state, line)
        elif line.kind == "tag":
            apply_media_tag(playlist, state, line)
    playlist.trailing_parts = state.parts
    return playlist


def append_segment(playlist: MediaPlaylist, state: ParserState, line: PlaylistLine) -> None:
    skipped = (playlist.skip.skipped_segments or 0) if playlist.skip else 0
    playlist.segments.append(
        MediaSegment(
            uri=line.value or "",
            line_number=line.number,
            media_sequence_number=playlist.media_sequence + skipped + len(playlist.segments),
            duration=state.duration,
            title=state.title,
            byterange=state.byterange,
            discontinuity=state.discontinuity,
            gap=state.gap,
            program_date_time=state.program_date_time,
            bitrate=state.bitrate,
            key=state.active_key,
            segment_map=state.active_map,
            parts=state.parts,
            cue_lines=state.cue_lines,
        )
    )
    state.start_next_segment()


def apply_media_tag(playlist: MediaPlaylist, state: ParserState, line: PlaylistLine) -> None:
    attributes = parse_attribute_list(line.value or "")
    if apply_header_tag(playlist, line, attributes):
        return
    if line.name == "EXTINF":
        duration_text, _, title = (line.value or "").partition(",")
        state.duration = parse_decimal(duration_text)
        state.title = title or None
    elif line.name == "EXT-X-BYTERANGE":
        state.byterange = line.value
    elif line.name == "EXT-X-DISCONTINUITY":
        state.discontinuity = True
    elif line.name == "EXT-X-GAP":
        state.gap = True
    elif line.name == "EXT-X-PROGRAM-DATE-TIME":
        state.program_date_time = line.value
    elif line.name == "EXT-X-BITRATE":
        state.bitrate = parse_integer(line.value)
    elif line.name == "EXT-X-KEY":
        state.active_key = parse_key_tag(line)
    elif line.name == "EXT-X-MAP":
        state.active_map = MapTag(
            line_number=line.number,
            uri=attributes.get("URI"),
            byterange=attributes.get("BYTERANGE"),
        )
    elif line.name == "EXT-X-PART":
        state.parts.append(
            PartTag(
                line_number=line.number,
                uri=attributes.get("URI"),
                duration=parse_decimal(attributes.get("DURATION")),
                independent=attributes.get("INDEPENDENT") == "YES",
                gap=attributes.get("GAP") == "YES",
                byterange=attributes.get("BYTERANGE"),
            )
        )
    elif line.name in AD_CUE_TAGS:
        state.cue_lines.append(line.number)
    elif not line.is_known_tag:
        playlist.unknown_tag_lines.append(line.number)


def apply_header_tag(
    playlist: MediaPlaylist, line: PlaylistLine, attributes: dict[str, str]
) -> bool:
    if line.name == "EXT-X-VERSION":
        playlist.version = parse_integer(line.value)
    elif line.name == "EXT-X-TARGETDURATION":
        playlist.target_duration = parse_integer(line.value)
    elif line.name == "EXT-X-MEDIA-SEQUENCE":
        playlist.media_sequence = parse_integer(line.value) or 0
    elif line.name == "EXT-X-DISCONTINUITY-SEQUENCE":
        playlist.discontinuity_sequence = parse_integer(line.value) or 0
    elif line.name == "EXT-X-PLAYLIST-TYPE":
        playlist.playlist_type = line.value
    elif line.name == "EXT-X-ENDLIST":
        playlist.endlist = True
    elif line.name == "EXT-X-I-FRAMES-ONLY":
        playlist.iframes_only = True
    elif line.name == "EXT-X-SERVER-CONTROL":
        playlist.server_control = ServerControlTag(
            line_number=line.number,
            can_skip_until=parse_decimal(attributes.get("CAN-SKIP-UNTIL")),
            can_block_reload=attributes.get("CAN-BLOCK-RELOAD") == "YES",
            hold_back=parse_decimal(attributes.get("HOLD-BACK")),
            part_hold_back=parse_decimal(attributes.get("PART-HOLD-BACK")),
        )
    elif line.name == "EXT-X-PART-INF":
        playlist.part_target = parse_decimal(attributes.get("PART-TARGET"))
    elif line.name == "EXT-X-SKIP":
        playlist.skip = SkipTag(
            line_number=line.number,
            skipped_segments=parse_integer(attributes.get("SKIPPED-SEGMENTS")),
        )
    elif line.name == "EXT-X-DATERANGE":
        playlist.dateranges.append(build_daterange(line, attributes))
    elif line.name == "EXT-X-PRELOAD-HINT":
        playlist.preload_hints.append(
            PreloadHintTag(
                line_number=line.number,
                hint_type=attributes.get("TYPE"),
                uri=attributes.get("URI"),
            )
        )
    elif line.name == "EXT-X-RENDITION-REPORT":
        playlist.rendition_reports.append(
            RenditionReportTag(
                line_number=line.number,
                uri=attributes.get("URI"),
                last_msn=parse_integer(attributes.get("LAST-MSN")),
                last_part=parse_integer(attributes.get("LAST-PART")),
            )
        )
    else:
        return False
    return True


def build_daterange(line: PlaylistLine, attributes: dict[str, str]) -> DateRangeTag:
    return DateRangeTag(
        line_number=line.number,
        range_id=attributes.get("ID"),
        range_class=attributes.get("CLASS"),
        start_date=attributes.get("START-DATE"),
        end_date=attributes.get("END-DATE"),
        duration=parse_decimal(attributes.get("DURATION")),
        planned_duration=parse_decimal(attributes.get("PLANNED-DURATION")),
        end_on_next=attributes.get("END-ON-NEXT") == "YES",
        attributes=attributes,
    )
