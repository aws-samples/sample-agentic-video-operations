from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from media_ops_contracts.approved_action import ActionProposal
from media_ops_contracts.stream_event import (
    STREAM_EVENT_ADAPTER,
    ApprovalRequested,
    BaseStreamEvent,
    ErrorEvent,
    FinalAnswer,
    encode_stream_event,
)
from media_ops_contracts.tool_failure import FailureKind

SESSION = "s" * 33


def test_events_round_trip_through_the_discriminated_union():
    events = [
        FinalAnswer(session_id=SESSION, text="Input loss on pipeline 0."),
        ErrorEvent(
            session_id=SESSION,
            kind=FailureKind.RESOURCE_NOT_FOUND,
            message="describe_channel failed",
            next_action="Check the channel id.",
        ),
        ApprovalRequested(
            session_id=SESSION,
            approval_id="ap-1",
            proposal=ActionProposal(actor_id="op", action="stop_channel", resource_id="1"),
            risk="high",
            expires_at=datetime(2026, 10, 5, 12, 10, tzinfo=UTC),
        ),
    ]
    for event in events:
        assert STREAM_EVENT_ADAPTER.validate_json(encode_stream_event(event)) == event


def test_events_are_encoded_once_as_a_json_object():
    encoded = encode_stream_event(FinalAnswer(session_id=SESSION, text="ok"))
    assert encoded.startswith("{")
    assert '"type":"final_answer"' in encoded


def test_encoding_rejects_a_bare_base_event_that_is_not_a_union_member():
    with pytest.raises(ValidationError):
        encode_stream_event(BaseStreamEvent(session_id=SESSION))
