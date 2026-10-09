"""Find the ffprobe binary, or explain how to get it."""

import shutil

from media_ops_contracts.tool_failure import FailureKind, ToolFailure


def locate_ffprobe() -> str:
    """The absolute path to ffprobe; raises with an install hint when absent."""
    path = shutil.which("ffprobe")
    if path is None:
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            "ffprobe is not installed, so media content cannot be probed.",
            "Install FFmpeg (https://ffmpeg.org/download.html); every other check"
            " still works without it.",
        )
    return path
