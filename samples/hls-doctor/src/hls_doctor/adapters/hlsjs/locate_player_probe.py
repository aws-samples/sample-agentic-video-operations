"""Check the optional hls.js harness prerequisites: Node 20+ and its node_modules."""

import shutil
from pathlib import Path

from media_ops_contracts.tool_failure import FailureKind, ToolFailure

HARNESS_DIR = Path(__file__).resolve().parents[4] / "player-probe"


def locate_player_probe() -> tuple[str, Path]:
    """(node binary, harness script path); raises with setup guidance when absent."""
    node = shutil.which("node")
    if node is None:
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            "The player probe needs Node.js 20 or newer, which is not installed.",
            "Install Node.js, run `npm install` in samples/hls-doctor/player-probe,"
            " and retry; every other check works without it.",
        )
    if not (HARNESS_DIR / "node_modules").is_dir():
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            "The player probe's dependencies are not installed.",
            "Run `npm install` in samples/hls-doctor/player-probe and retry;"
            " every other check works without it.",
        )
    return node, HARNESS_DIR / "probe_stream.mjs"
