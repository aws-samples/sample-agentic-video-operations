"""Decode a service's base64 thumbnail, or fail with a typed, sanitized error.

MediaLive and MediaConnect both return thumbnails as base64 text. Invalid text must not
reach the image library as bytes, and the error must not quote what the service sent.
"""

import base64
import binascii

from media_ops_contracts.tool_failure import FailureKind, ToolFailure


def decode_thumbnail(image_base64: str) -> bytes:
    try:
        return base64.b64decode(image_base64, validate=True)
    except (binascii.Error, ValueError):
        raise invalid_thumbnail() from None


def invalid_thumbnail() -> ToolFailure:
    return ToolFailure(
        FailureKind.UNEXPECTED_FAILURE,
        "The service returned a thumbnail that is not a valid image.",
        "Retry the read; if it persists, check the resource's thumbnail settings.",
    )
