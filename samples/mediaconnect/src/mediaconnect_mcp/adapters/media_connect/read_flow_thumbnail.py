"""Read the current thumbnail bytes for one MediaConnect flow."""

from datetime import datetime
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel

from media_ops_contracts.classify_aws_error import classify_aws_error
from media_ops_contracts.tool_failure import FailureKind, ToolFailure

# The thumbnail call's own refusal: this flow's source or monitoring has no thumbnail, and
# asking again in the same window won't change that. A busy or unavailable service
# (throttling, 5xx, a timeout) is the opposite: the next poll may well answer.
CONCLUSIVE = ("BadRequestException", "NotFoundException")


class ThumbnailUnavailable(ToolFailure):
    """No image. `conclusive` when the service refused, not when it just had none yet."""

    def __init__(self, kind: FailureKind, message: str, *, conclusive: bool) -> None:
        super().__init__(
            kind, message, "Confirm the flow is active and source thumbnails are enabled."
        )
        self.conclusive = conclusive


class FlowThumbnail(BaseModel):
    flow_arn: str
    image_base64: str
    observed_at: datetime | None = None
    timecode: str | None = None
    messages: list[str]


def read_flow_thumbnail(media_connect: Any, flow_arn: str) -> FlowThumbnail:
    """Return the current JPEG thumbnail without exposing it as tool output."""
    try:
        response = media_connect.describe_flow_source_thumbnail(FlowArn=flow_arn)
    except (BotoCoreError, ClientError) as error:
        raise _no_thumbnail_or_failure(error) from error
    details = response.get("ThumbnailDetails", {})
    image = details.get("Thumbnail")
    messages = [describe_message(message) for message in details.get("ThumbnailMessages", [])]
    if not image:
        reason = f": {'; '.join(messages)}" if messages else ""
        raise ThumbnailUnavailable(
            FailureKind.RESOURCE_NOT_FOUND,
            f"No thumbnail is available for this flow{reason}.",
            conclusive=False,
        )
    return FlowThumbnail(
        flow_arn=details.get("FlowArn", flow_arn),
        image_base64=image,
        observed_at=details.get("Timestamp"),
        timecode=details.get("Timecode"),
        messages=messages,
    )


def _no_thumbnail_or_failure(error: BotoCoreError | ClientError) -> ToolFailure:
    """Conclusive or transient absence (the sampler decides), or any other typed failure.

    Messages are a fixed sentence and the code, not the service's free text, as in
    classify_aws_error.
    """
    failure = classify_aws_error(error, operation="Read MediaConnect flow thumbnail")
    code = error.response.get("Error", {}).get("Code", "") if isinstance(error, ClientError) else ""
    if code in CONCLUSIVE:
        return ThumbnailUnavailable(
            failure.kind,
            f"MediaConnect has no source thumbnail for this flow ({code}): its source or "
            "monitoring configuration doesn't provide one.",
            conclusive=True,
        )
    if failure.kind is FailureKind.EXTERNAL_SERVICE_UNAVAILABLE:
        return ThumbnailUnavailable(
            failure.kind,
            f"MediaConnect was busy or unavailable for the thumbnail read "
            f"({code or type(error).__name__}).",
            conclusive=False,
        )
    return failure


def describe_message(message: Any) -> str:
    """ThumbnailMessages are MessageDetail objects (Code, Message, ResourceName)."""
    if not isinstance(message, dict):
        return str(message)
    return ": ".join(str(part) for part in (message.get("Code"), message.get("Message")) if part)
