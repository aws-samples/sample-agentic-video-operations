"""Find Apple's mediastreamvalidator, or explain that the crosscheck is optional."""

import shutil

from media_ops_contracts.tool_failure import FailureKind, ToolFailure


def locate_mediastreamvalidator() -> str:
    """The absolute path to mediastreamvalidator; raises when it is not installed."""
    path = shutil.which("mediastreamvalidator")
    if path is None:
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            "Apple's mediastreamvalidator is not installed (macOS HLS Tools).",
            "Install Apple's HLS Tools to add the conformance crosscheck; every"
            " other check still works without it.",
        )
    return path
