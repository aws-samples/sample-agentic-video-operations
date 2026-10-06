"""Describe a JPEG thumbnail with a Bedrock vision model through Converse."""

import base64
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel

from media_ops_contracts.classify_aws_error import classify_aws_error
from media_ops_contracts.tool_failure import FailureKind, ToolFailure


class ThumbnailDescription(BaseModel):
    text: str
    model_id: str


def describe_thumbnail(
    bedrock: Any,
    image_base64: str,
    model_id: str,
) -> ThumbnailDescription:
    """Return an operational description without returning the image bytes."""
    try:
        response = bedrock.converse(
            modelId=model_id,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "text": (
                                "Describe the live-video frame. Lead with visible service impact, "
                                "then cite black/frozen frames, color bars, text, artifacts, or "
                                "other evidence. Say when the image alone is insufficient."
                            )
                        },
                        {
                            "image": {
                                "format": "jpeg",
                                "source": {"bytes": base64.b64decode(image_base64)},
                            }
                        },
                    ],
                }
            ],
            inferenceConfig={"maxTokens": 700},
        )
    except (BotoCoreError, ClientError) as error:
        raise classify_aws_error(error, operation="Describe thumbnail with Bedrock") from error
    content = response.get("output", {}).get("message", {}).get("content", [])
    text = content[0].get("text") if content and isinstance(content[0], dict) else None
    if not text:
        raise ToolFailure(
            FailureKind.UNEXPECTED_FAILURE,
            "The thumbnail model returned no description.",
            "Retry the thumbnail analysis and inspect the Bedrock response logs.",
        )
    return ThumbnailDescription(text=text, model_id=model_id)
