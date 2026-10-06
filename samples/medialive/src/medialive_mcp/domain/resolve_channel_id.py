"""Pick the channel a request is about: the explicit id, else the configured default."""

from media_ops_contracts.tool_failure import FailureKind, ToolFailure


def resolve_channel_id(channel_id: str | None, default_channel_id: str) -> str:
    resolved = channel_id or default_channel_id
    if not resolved:
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            "No channel_id given and MEDIALIVE_CHANNEL_ID is not set.",
            "Pass channel_id (see list_channels) or set MEDIALIVE_CHANNEL_ID in the root .env.",
        )
    return resolved
