"""The vision rubric: structured, retried once, otherwise unavailable, never a guess."""

import pytest
from botocore.exceptions import ClientError

from media_ops_video_quality.score_with_vision import (
    MAX_FRAMES,
    RUBRIC_TOOL,
    describe_frame,
    score_with_vision,
)

GOOD = {
    "compression_artifacts": 4, "banding": 5, "interlacing_ghosting": 5, "slate_or_bars": 5,
    "overall": 4, "confidence": 0.8, "evidence": "Programme video, mild softness.",
}  # fmt: skip


def answer(tool_input):
    use = {"toolUseId": "t", "name": RUBRIC_TOOL, "input": tool_input}
    return {"output": {"message": {"content": [{"toolUse": use}]}}}


class FakeBedrock:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests = []

    def converse(self, **request):
        self.requests.append(request)
        result = self.answers.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def test_a_valid_rubric_is_ok_and_the_tool_call_is_forced():
    bedrock = FakeBedrock(answer(GOOD))
    scores, status = score_with_vision(bedrock, "model", [b"jpeg"] * 3)
    assert status == "ok" and scores.overall == 4
    [request] = bedrock.requests
    assert request["toolConfig"]["toolChoice"] == {"tool": {"name": RUBRIC_TOOL}}
    assert sum("image" in block for block in request["messages"][0]["content"]) == 3


def test_an_invalid_answer_is_retried_once():
    bedrock = FakeBedrock(answer({**GOOD, "overall": 9}), answer(GOOD))
    scores, status = score_with_vision(bedrock, "model", [b"jpeg"])
    assert status == "ok" and len(bedrock.requests) == 2


def test_two_invalid_answers_or_prose_are_unavailable():
    prose = {"output": {"message": {"content": [{"text": "Looks fine to me."}]}}}
    for answers in ((answer({"overall": 3}), answer({"overall": 3})), (prose, prose)):
        scores, status = score_with_vision(FakeBedrock(*answers), "model", [b"jpeg"])
        assert (scores, status) == (None, "unavailable")


def test_a_service_error_or_no_model_is_unavailable():
    denied = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "Converse")
    assert score_with_vision(FakeBedrock(denied), "model", [b"jpeg"]) == (None, "unavailable")
    assert score_with_vision(FakeBedrock(), None, [b"jpeg"]) == (None, "unavailable")
    assert score_with_vision(FakeBedrock(), "model", []) == (None, "unavailable")


def test_at_most_twenty_images_are_sent():
    bedrock = FakeBedrock(answer(GOOD))
    score_with_vision(bedrock, "model", [b"jpeg"] * 30)
    blocks = bedrock.requests[0]["messages"][0]["content"]
    assert sum("image" in block for block in blocks) == MAX_FRAMES


def test_describe_frame_returns_the_models_text():
    text = {"output": {"message": {"content": [{"text": "Colour bars."}]}}}
    assert describe_frame(FakeBedrock(text), "model", b"jpeg", "Describe.") == "Colour bars."


def test_describe_frame_with_no_text_is_a_typed_failure():
    from media_ops_contracts.tool_failure import FailureKind, ToolFailure

    class Empty:
        def converse(self, **_):
            return {"output": {"message": {"content": []}}}

    with pytest.raises(ToolFailure) as failure:
        describe_frame(Empty(), "model", b"jpeg", "Describe.")
    assert failure.value.kind is FailureKind.UNEXPECTED_FAILURE
