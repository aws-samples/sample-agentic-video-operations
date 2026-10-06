"""Read a pipeline thumbnail and describe it (two adapters, one user-visible answer)."""

from pydantic import BaseModel

from media_ops_contracts.tool_failure import FailureKind, ToolFailure
from media_ops_video_quality.decode_thumbnail import decode_thumbnail
from media_ops_video_quality.score_with_vision import describe_frame
from medialive_mcp.adapters.media_live.read_channel_thumbnail import read_channel_thumbnail
from medialive_mcp.bootstrap.create_medialive_clients import MediaLiveClients
from medialive_mcp.prompts.analyze_thumbnail_prompt import ANALYZE_THUMBNAIL_PROMPT


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
    frame = decode_thumbnail(thumbnail.image_base64)
    description = describe_frame(clients.bedrock, model_id, frame, ANALYZE_THUMBNAIL_PROMPT)
    return ThumbnailDescription(
        channel_id=channel_id,
        pipeline_id=pipeline_id,
        taken_at=thumbnail.taken_at,
        description=description,
        model_id=model_id,
    )
