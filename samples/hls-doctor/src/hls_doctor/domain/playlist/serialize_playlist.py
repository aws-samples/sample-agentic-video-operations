"""Rebuild playlist text from tokenized lines, byte-for-byte."""

from hls_doctor.domain.playlist.playlist_line import PlaylistLine


def serialize_playlist(lines: list[PlaylistLine]) -> str:
    """The inverse of tokenize_playlist: unknown syntax survives untouched."""
    return "\n".join(line.raw for line in lines)
