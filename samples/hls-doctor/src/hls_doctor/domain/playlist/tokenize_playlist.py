"""Split playlist text into raw lines. Nothing is interpreted or dropped here."""

from hls_doctor.domain.playlist.playlist_line import PlaylistLine


def tokenize_playlist(text: str) -> list[PlaylistLine]:
    """Every input line becomes one PlaylistLine; `raw` round-trips verbatim."""
    lines: list[PlaylistLine] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            lines.append(PlaylistLine(number=number, kind="blank", raw=raw))
        elif stripped.startswith("#EXT"):
            name, _, value = stripped[1:].partition(":")
            lines.append(
                PlaylistLine(number=number, kind="tag", raw=raw, name=name, value=value or None)
            )
        elif stripped.startswith("#"):
            lines.append(PlaylistLine(number=number, kind="comment", raw=raw))
        else:
            lines.append(PlaylistLine(number=number, kind="uri", raw=raw, value=stripped))
    return lines
