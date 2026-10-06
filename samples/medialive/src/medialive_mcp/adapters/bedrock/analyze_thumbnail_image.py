"""Describe a JPEG thumbnail with a Bedrock vision model through the Converse API."""

import base64
from typing import Any

from media_ops_contracts.call_aws_operation import call_aws_operation
from medialive_mcp.prompts.analyze_thumbnail_prompt import ANALYZE_THUMBNAIL_PROMPT


def analyze_thumbnail_image(bedrock: Any, image_base64: str, model_id: str) -> str:
    response = call_aws_operation(
        bedrock,
        "converse",
        modelId=model_id,
        messages=[
            {
                "role": "user",
                "content": [
                    {"text": ANALYZE_THUMBNAIL_PROMPT},
                    {
                        "image": {
                            "format": "jpeg",
                            "source": {"bytes": base64.b64decode(image_base64)},
                        }
                    },
                ],
            }
        ],
        inferenceConfig={"maxTokens": 600},
    )
    return response["output"]["message"]["content"][0]["text"]
