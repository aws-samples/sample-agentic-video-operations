"""Typed model of a Media Playlist, including LL-HLS and date-range structures."""

from pydantic import BaseModel, Field


class KeyTag(BaseModel):
    line_number: int
    method: str | None = None
    uri: str | None = None
    iv: str | None = None
    keyformat: str | None = None
    keyformatversions: str | None = None


class MapTag(BaseModel):
    line_number: int
    uri: str | None = None
    byterange: str | None = None


class PartTag(BaseModel):
    line_number: int
    uri: str | None = None
    duration: float | None = None
    independent: bool = False
    gap: bool = False
    byterange: str | None = None


class DateRangeTag(BaseModel):
    line_number: int
    range_id: str | None = None
    range_class: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    duration: float | None = None
    planned_duration: float | None = None
    end_on_next: bool = False
    attributes: dict[str, str] = Field(default_factory=dict)


class PreloadHintTag(BaseModel):
    line_number: int
    hint_type: str | None = None
    uri: str | None = None


class RenditionReportTag(BaseModel):
    line_number: int
    uri: str | None = None
    last_msn: int | None = None
    last_part: int | None = None


class ServerControlTag(BaseModel):
    line_number: int
    can_skip_until: float | None = None
    can_block_reload: bool = False
    hold_back: float | None = None
    part_hold_back: float | None = None


class SkipTag(BaseModel):
    line_number: int
    skipped_segments: int | None = None
    recently_removed_dateranges: bool = False


class MediaSegment(BaseModel):
    uri: str
    line_number: int
    media_sequence_number: int
    duration: float | None = None
    title: str | None = None
    byterange: str | None = None
    discontinuity: bool = False
    gap: bool = False
    program_date_time: str | None = None
    bitrate: int | None = None
    key: KeyTag | None = None
    segment_map: MapTag | None = None
    parts: list[PartTag] = Field(default_factory=list)
    cue_lines: list[int] = Field(default_factory=list)


class MediaPlaylist(BaseModel):
    version: int | None = None
    target_duration: int | None = None
    media_sequence: int = 0
    discontinuity_sequence: int = 0
    playlist_type: str | None = None
    endlist: bool = False
    iframes_only: bool = False
    server_control: ServerControlTag | None = None
    part_target: float | None = None
    skip: SkipTag | None = None
    segments: list[MediaSegment] = Field(default_factory=list)
    trailing_parts: list[PartTag] = Field(default_factory=list)
    dateranges: list[DateRangeTag] = Field(default_factory=list)
    preload_hints: list[PreloadHintTag] = Field(default_factory=list)
    rendition_reports: list[RenditionReportTag] = Field(default_factory=list)
    unknown_tag_lines: list[int] = Field(default_factory=list)
