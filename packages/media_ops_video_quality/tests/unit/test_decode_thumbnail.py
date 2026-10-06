"""Thumbnails from either service: valid base64 of an image, or a typed, sanitized failure."""

import base64
import io

import pytest
from PIL import Image

from media_ops_contracts.tool_failure import FailureKind, ToolFailure
from media_ops_video_quality.decode_thumbnail import decode_thumbnail
from media_ops_video_quality.measure_frame import measure_frame


def jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 36), (40, 90, 160)).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_valid_base64_decodes_to_the_image_bytes():
    assert decode_thumbnail(base64.b64encode(jpeg()).decode()) == jpeg()


@pytest.mark.parametrize("text", ["<<SECRET-PAYLOAD>>", "abc", "not base64 at all!"])
def test_invalid_base64_is_a_typed_failure_that_quotes_nothing(text):
    with pytest.raises(ToolFailure) as failure:
        decode_thumbnail(text)

    assert failure.value.kind is FailureKind.UNEXPECTED_FAILURE
    assert text not in f"{failure.value.message} {failure.value.next_action}"


def test_bytes_that_are_not_an_image_are_a_typed_failure():
    with pytest.raises(ToolFailure) as failure:
        measure_frame(b"valid base64 once, but not an image")

    assert failure.value.kind is FailureKind.UNEXPECTED_FAILURE
