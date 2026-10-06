"""Typed model of a Multivariant Playlist. Raw attributes ride along untouched."""

from pydantic import BaseModel, Field


class VariantStream(BaseModel):
    uri: str
    line_number: int
    bandwidth: int | None = None
    average_bandwidth: int | None = None
    codecs: str | None = None
    resolution: tuple[int, int] | None = None
    frame_rate: float | None = None
    video_range: str | None = None
    audio: str | None = None
    video: str | None = None
    subtitles: str | None = None
    closed_captions: str | None = None
    pathway_id: str | None = None
    stable_variant_id: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)
    iframe_only: bool = False


class Rendition(BaseModel):
    media_type: str
    line_number: int
    group_id: str | None = None
    name: str | None = None
    uri: str | None = None
    language: str | None = None
    assoc_language: str | None = None
    default: bool = False
    autoselect: bool = False
    forced: bool = False
    instream_id: str | None = None
    characteristics: str | None = None
    channels: str | None = None
    stable_rendition_id: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)


class SessionKeyTag(BaseModel):
    line_number: int
    method: str | None = None
    uri: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)


class SessionDataTag(BaseModel):
    line_number: int
    data_id: str | None = None
    value: str | None = None
    uri: str | None = None
    language: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)


class ContentSteeringTag(BaseModel):
    line_number: int
    server_uri: str | None = None
    pathway_id: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)


class DefineTag(BaseModel):
    line_number: int
    name: str | None = None
    value: str | None = None
    import_name: str | None = None
    queryparam: str | None = None


class MultivariantPlaylist(BaseModel):
    version: int | None = None
    independent_segments: bool = False
    variants: list[VariantStream] = Field(default_factory=list)
    renditions: list[Rendition] = Field(default_factory=list)
    session_keys: list[SessionKeyTag] = Field(default_factory=list)
    session_data: list[SessionDataTag] = Field(default_factory=list)
    steering: ContentSteeringTag | None = None
    defines: list[DefineTag] = Field(default_factory=list)
    unknown_tag_lines: list[int] = Field(default_factory=list)
