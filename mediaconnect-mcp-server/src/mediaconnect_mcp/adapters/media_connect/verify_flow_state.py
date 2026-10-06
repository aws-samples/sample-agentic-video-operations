"""Poll a MediaConnect flow until it reaches the requested state."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from mediaconnect_mcp.adapters.media_connect.describe_flow import (
    FlowDetails,
    FlowState,
    describe_flow,
)


@dataclass(frozen=True)
class FlowPoller:
    timeout_seconds: float = 120
    interval_seconds: float = 5
    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep


DEFAULT_FLOW_POLLER = FlowPoller()


class FlowActionResult(BaseModel):
    action: str
    resource_id: str
    before: FlowDetails
    after: FlowDetails
    verified: bool


def verify_flow_state(
    media_connect: Any,
    flow_arn: str,
    expected: FlowState,
    poller: FlowPoller = DEFAULT_FLOW_POLLER,
) -> FlowDetails:
    """Return the last observed state after a bounded verification poll."""
    deadline = poller.monotonic() + poller.timeout_seconds
    observed = describe_flow(media_connect, flow_arn)
    while observed.state is not expected and poller.monotonic() < deadline:
        poller.sleep(poller.interval_seconds)
        observed = describe_flow(media_connect, flow_arn)
    return observed
