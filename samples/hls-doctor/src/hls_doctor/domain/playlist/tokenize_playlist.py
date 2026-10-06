"""Split playlist text into raw lines. Nothing is interpreted or dropped here.

Explicit caps bound hostile input independently of the HTTP body cap: too
many lines or an absurdly long line is a typed failure, not an OOM.
"""

from hls_doctor.domain.playlist.playlist_line import PlaylistLine
from media_ops_contracts.tool_failure import FailureKind, ToolFailure

MAX_PLAYLIST_LINES = 20_000
MAX_LINE_CHARS = 16_384


def tokenize_playlist(text: str) -> list[PlaylistLine]:
    """Every input line becomes one PlaylistLine; `raw` round-trips verbatim."""
    lines: list[PlaylistLine] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if number > MAX_PLAYLIST_LINES:
            raise ToolFailure(
                FailureKind.INVALID_REQUEST,
                f"The playlist exceeds {MAX_PLAYLIST_LINES} lines.",
                "This is not a playlist a client could use; inspect the URL manually.",
            )
        if len(raw) > MAX_LINE_CHARS:
            raise ToolFailure(
                FailureKind.INVALID_REQUEST,
                f"Playlist line {number} exceeds {MAX_LINE_CHARS} characters.",
                "This is not a playlist a client could use; inspect the URL manually.",
            )
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
