"""Read a pipeline thumbnail and describe it (two adapters, one user-visible answer)."""

from pydantic import BaseModel

from media_ops_contracts.tool_failure import FailureKind, ToolFailure
from medialive_mcp.adapters.bedrock.analyze_thumbnail_image import analyze_thumbnail_image
from medialive_mcp.adapters.media_live.read_channel_thumbnail import read_channel_thumbnail
from medialive_mcp.bootstrap.create_medialive_clients import MediaLiveClients


class ThumbnailDescription(BaseModel):
    channel_id: str
    pipeline_id: str
    taken_at: str | None
    description: str
    model_id: str


def describe_channel_thumbnail(
    clients: MediaLiveClients, channel_id: str, pipeline_id: str, model_id: str | None
) -> ThumbnailDescription:
    if not model_id:
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            "THUMBNAIL_MODEL_ID is not set.",
            "Set THUMBNAIL_MODEL_ID in the root .env (see .env.example).",
        )
    thumbnail = read_channel_thumbnail(clients.medialive, channel_id, pipeline_id)
    description = analyze_thumbnail_image(clients.bedrock, thumbnail.image_base64, model_id)
    return ThumbnailDescription(
        channel_id=channel_id,
        pipeline_id=pipeline_id,
        taken_at=thumbnail.taken_at,
        description=description,
        model_id=model_id,
    )
