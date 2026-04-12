"""Shared constants for EML MediaLive tools.

Single source of truth for the default channel ID and helper.
"""

import os
from typing import Optional

# Default channel ID — set via environment variable at install time
DEFAULT_CHANNEL_ID = os.getenv("MEDIALIVE_DEFAULT_CHANNEL_ID", "")


def get_channel_id(channel_id: Optional[str] = None) -> str:
    """Get channel ID. Uses DEFAULT_CHANNEL_ID env var if not specified."""
    resolved = channel_id or DEFAULT_CHANNEL_ID
    if not resolved:
        raise ValueError(
            "No channel_id provided and MEDIALIVE_DEFAULT_CHANNEL_ID is not set. "
            "Either pass channel_id explicitly or set the environment variable."
        )
    return resolved
