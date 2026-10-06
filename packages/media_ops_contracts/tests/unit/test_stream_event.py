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
    UsageReported,
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
        UsageReported(
            session_id=SESSION,
            model_id="us.anthropic.claude-sonnet-4-6",
            input_tokens=100,
            output_tokens=20,
            total_tokens=120,
            cache_read_input_tokens=40,
            cache_write_input_tokens=10,
            estimated_usd=0.0006,
        ),
    ]
    for event in events:
        payload = STREAM_EVENT_ADAPTER.dump_python(
            STREAM_EVENT_ADAPTER.validate_python(event),
            mode="json",
        )
        assert STREAM_EVENT_ADAPTER.validate_python(payload) == event


def test_the_union_rejects_a_bare_base_event():
    with pytest.raises(ValidationError):
        STREAM_EVENT_ADAPTER.validate_python(BaseStreamEvent(session_id=SESSION))


def test_usage_token_counts_cannot_be_negative():
    with pytest.raises(ValidationError):
        UsageReported(
            session_id=SESSION,
            model_id="us.anthropic.claude-sonnet-4-6",
            input_tokens=1,
            output_tokens=1,
            total_tokens=2,
            cache_read_input_tokens=-1,
            cache_write_input_tokens=0,
        )
