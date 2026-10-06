"""Hub-wide defaults for pack tools, set before the packs read their settings.

The hub answers inside one turn, so the visual quality tool samples a shorter window than
over MCP (8 frames in 20 s instead of 10 in 30 s). An explicit environment value wins.
"""

from collections.abc import MutableMapping

HUB_TOOL_DEFAULTS = {"VISUAL_QUALITY_FRAMES": "8", "VISUAL_QUALITY_WINDOW_SECONDS": "20"}


def apply_hub_tool_defaults(environ: MutableMapping[str, str]) -> None:
    for name, value in HUB_TOOL_DEFAULTS.items():
        environ.setdefault(name, value)
