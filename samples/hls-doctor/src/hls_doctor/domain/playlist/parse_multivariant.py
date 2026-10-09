"""Build the typed Multivariant model from tokenized lines."""

from hls_doctor.domain.playlist.media_playlist_model import KeyTag
from hls_doctor.domain.playlist.multivariant_model import (
    ContentSteeringTag,
    DefineTag,
    MultivariantPlaylist,
    Rendition,
    SessionDataTag,
    SessionKeyTag,
    VariantStream,
)
from hls_doctor.domain.playlist.parse_attribute_list import (
    parse_attribute_list,
    parse_decimal,
    parse_integer,
    parse_resolution,
)
from hls_doctor.domain.playlist.playlist_line import PlaylistLine


def build_variant(uri: str, line: PlaylistLine, *, iframe_only: bool) -> VariantStream:
    attributes = parse_attribute_list(line.value or "")
    return VariantStream(
        uri=uri,
        line_number=line.number,
        bandwidth=parse_integer(attributes.get("BANDWIDTH")),
        average_bandwidth=parse_integer(attributes.get("AVERAGE-BANDWIDTH")),
        codecs=attributes.get("CODECS"),
        resolution=parse_resolution(attributes.get("RESOLUTION")),
        frame_rate=parse_decimal(attributes.get("FRAME-RATE")),
        video_range=attributes.get("VIDEO-RANGE"),
        audio=attributes.get("AUDIO"),
        video=attributes.get("VIDEO"),
        subtitles=attributes.get("SUBTITLES"),
        closed_captions=attributes.get("CLOSED-CAPTIONS"),
        pathway_id=attributes.get("PATHWAY-ID"),
        stable_variant_id=attributes.get("STABLE-VARIANT-ID"),
        attributes=attributes,
        iframe_only=iframe_only,
    )


def build_rendition(line: PlaylistLine) -> Rendition:
    attributes = parse_attribute_list(line.value or "")
    return Rendition(
        media_type=attributes.get("TYPE", ""),
        line_number=line.number,
        group_id=attributes.get("GROUP-ID"),
        name=attributes.get("NAME"),
        uri=attributes.get("URI"),
        language=attributes.get("LANGUAGE"),
        assoc_language=attributes.get("ASSOC-LANGUAGE"),
        default=attributes.get("DEFAULT") == "YES",
        autoselect=attributes.get("AUTOSELECT") == "YES",
        forced=attributes.get("FORCED") == "YES",
        instream_id=attributes.get("INSTREAM-ID"),
        characteristics=attributes.get("CHARACTERISTICS"),
        channels=attributes.get("CHANNELS"),
        stable_rendition_id=attributes.get("STABLE-RENDITION-ID"),
        attributes=attributes,
    )


def build_define(line: PlaylistLine) -> DefineTag:
    attributes = parse_attribute_list(line.value or "")
    return DefineTag(
        line_number=line.number,
        name=attributes.get("NAME"),
        value=attributes.get("VALUE"),
        import_name=attributes.get("IMPORT"),
        queryparam=attributes.get("QUERYPARAM"),
    )


def parse_multivariant(lines: list[PlaylistLine]) -> MultivariantPlaylist:
    playlist = MultivariantPlaylist()
    pending_variant: PlaylistLine | None = None
    for line in lines:
        if line.kind == "uri" and pending_variant is not None:
            playlist.variants.append(
                build_variant(line.value or "", pending_variant, iframe_only=False)
            )
            pending_variant = None
        elif line.kind == "tag":
            pending_variant = apply_multivariant_tag(playlist, line, pending_variant)
    return playlist


def apply_multivariant_tag(
    playlist: MultivariantPlaylist, line: PlaylistLine, pending: PlaylistLine | None
) -> PlaylistLine | None:
    attributes = parse_attribute_list(line.value or "")
    if line.name == "EXT-X-STREAM-INF":
        return line
    if line.name == "EXT-X-I-FRAME-STREAM-INF":
        playlist.variants.append(build_variant(attributes.get("URI", ""), line, iframe_only=True))
    elif line.name == "EXT-X-MEDIA":
        playlist.renditions.append(build_rendition(line))
    elif line.name == "EXT-X-VERSION":
        playlist.version = parse_integer(line.value)
    elif line.name == "EXT-X-INDEPENDENT-SEGMENTS":
        playlist.independent_segments = True
    elif line.name == "EXT-X-SESSION-KEY":
        key = build_session_key(line, attributes)
        playlist.session_keys.append(key)
    elif line.name == "EXT-X-SESSION-DATA":
        playlist.session_data.append(build_session_data(line, attributes))
    elif line.name == "EXT-X-CONTENT-STEERING":
        playlist.steering = ContentSteeringTag(
            line_number=line.number,
            server_uri=attributes.get("SERVER-URI"),
            pathway_id=attributes.get("PATHWAY-ID"),
            attributes=attributes,
        )
    elif line.name == "EXT-X-DEFINE":
        playlist.defines.append(build_define(line))
    elif not line.is_known_tag:
        playlist.unknown_tag_lines.append(line.number)
    return pending


def build_session_key(line: PlaylistLine, attributes: dict[str, str]) -> SessionKeyTag:
    return SessionKeyTag(
        line_number=line.number,
        method=attributes.get("METHOD"),
        uri=attributes.get("URI"),
        attributes=attributes,
    )


def build_session_data(line: PlaylistLine, attributes: dict[str, str]) -> SessionDataTag:
    return SessionDataTag(
        line_number=line.number,
        data_id=attributes.get("DATA-ID"),
        value=attributes.get("VALUE"),
        uri=attributes.get("URI"),
        language=attributes.get("LANGUAGE"),
        attributes=attributes,
    )


def parse_key_tag(line: PlaylistLine) -> KeyTag:
    attributes = parse_attribute_list(line.value or "")
    return KeyTag(
        line_number=line.number,
        method=attributes.get("METHOD"),
        uri=attributes.get("URI"),
        iv=attributes.get("IV"),
        keyformat=attributes.get("KEYFORMAT"),
        keyformatversions=attributes.get("KEYFORMATVERSIONS"),
    )
