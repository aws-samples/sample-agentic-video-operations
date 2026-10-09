"""Create one transient signal map, read its graph, and always delete it (§8.3).

The map is a discovery engine, not storage: it is created tagged, polled until it completes,
read once, and deleted in a `finally` on every path. Its deletion is then verified, because a
map left behind counts against the account's quota and is the operator's to remove by hand.
"""

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from media_ops_contracts.call_aws_operation import call_aws_operation
from media_ops_contracts.tool_failure import FailureKind, ToolFailure

LOGGER = logging.getLogger("agentic_iops_streaming")

APP_TAG = {"managed-by": "agentic-iops-streaming"}
NAME_PREFIX = "agentic-iops-"
MAX_NAME_LENGTH = 255
CREATE_IN_PROGRESS = "CREATE_IN_PROGRESS"
CREATE_COMPLETE = "CREATE_COMPLETE"
POLL_INTERVAL_SECONDS = 5.0
DEADLINE_SECONDS = 120.0


@dataclass(frozen=True)
class SignalMapReading:
    """What one completed map said, plus the id it had while it existed."""

    identifier: str
    status: str
    media_resource_map: dict[str, Any]
    failed_media_resource_map: dict[str, Any]
    error_message: str | None = None


@dataclass(frozen=True)
class DiscoveryPolicy:
    """How long discovery may poll, and how it waits (injected so tests never sleep)."""

    deadline_seconds: float = DEADLINE_SECONDS
    interval_seconds: float = POLL_INTERVAL_SECONDS
    sleep: Callable[[float], None] = field(default=time.sleep)
    monotonic: Callable[[], float] = field(default=time.monotonic)


class CleanupFailure(Exception):
    """The map could not be proven deleted. Carries the sentence the operator needs."""

    def __init__(self, identifier: str, kind: FailureKind) -> None:
        super().__init__(identifier)
        self.identifier = identifier
        self.kind = kind

    @property
    def sentence(self) -> str:
        return f"Signal map {self.identifier!r} was not deleted ({self.kind.value})."

    @property
    def next_action(self) -> str:
        return (
            "Delete it in the MediaLive console (Workflow monitor → Signal maps) or with"
            f" `aws medialive delete-signal-map --identifier {self.identifier}`."
        )


def discover_signal_map(
    medialive: Any,
    *,
    entry_point_arn: str,
    workflow_id: str,
    policy: DiscoveryPolicy | None = None,
) -> SignalMapReading:
    """Create, wait, read, then delete. Raises ToolFailure; never leaves a map unreported."""
    policy = policy or DiscoveryPolicy()
    created = call_aws_operation(
        medialive,
        "create_signal_map",
        DiscoveryEntryPointArn=entry_point_arn,
        Name=build_map_name(workflow_id),
        Tags=dict(APP_TAG),
        RequestId=str(uuid.uuid4()),
    )
    identifier = str(created.get("Id") or "")
    if not identifier:
        raise ToolFailure(
            FailureKind.UNEXPECTED_FAILURE,
            "MediaLive created a signal map without returning its id.",
            "Retry the discovery; report the issue if it happens again.",
        )
    primary: ToolFailure | None = None
    try:
        return wait_for_discovery(medialive, identifier, policy)
    except ToolFailure as failure:
        primary = failure
        raise
    finally:
        report_cleanup(medialive, identifier, primary)


def build_map_name(workflow_id: str) -> str:
    return f"{NAME_PREFIX}{workflow_id}"[:MAX_NAME_LENGTH]


def wait_for_discovery(
    medialive: Any, identifier: str, policy: DiscoveryPolicy
) -> SignalMapReading:
    """Poll until the map leaves CREATE_IN_PROGRESS, or the deadline passes."""
    deadline = policy.monotonic() + policy.deadline_seconds
    reading = read_signal_map(medialive, identifier)
    while reading.status == CREATE_IN_PROGRESS and policy.monotonic() < deadline:
        policy.sleep(policy.interval_seconds)
        reading = read_signal_map(medialive, identifier)
    if reading.status == CREATE_COMPLETE:
        return reading
    if reading.status == CREATE_IN_PROGRESS:
        raise ToolFailure(
            FailureKind.EXTERNAL_SERVICE_UNAVAILABLE,
            f"Discovery did not finish within {policy.deadline_seconds:.0f} s"
            f" (the map was still {reading.status}).",
            "Retry; a large presentation can take longer to map.",
        )
    raise ToolFailure(
        FailureKind.EXTERNAL_SERVICE_UNAVAILABLE,
        f"Discovery failed ({reading.status})"
        + (f": {reading.error_message}" if reading.error_message else "."),
        "Check that the entry point ARN is a live resource in this account and region.",
    )


def read_signal_map(medialive: Any, identifier: str) -> SignalMapReading:
    answer = call_aws_operation(medialive, "get_signal_map", Identifier=identifier)
    return SignalMapReading(
        identifier=str(answer.get("Id") or identifier),
        status=str(answer.get("Status") or ""),
        media_resource_map=answer.get("MediaResourceMap") or {},
        failed_media_resource_map=answer.get("FailedMediaResourceMap") or {},
        error_message=answer.get("ErrorMessage"),
    )


def report_cleanup(medialive: Any, identifier: str, primary: ToolFailure | None) -> None:
    """Delete and verify. A cleanup failure is raised, or attached to the primary failure."""
    try:
        delete_and_verify(medialive, identifier)
    except CleanupFailure as cleanup:
        LOGGER.warning(
            "signal map not deleted",
            extra={"signal_map.id": cleanup.identifier, "failure.kind": cleanup.kind.value},
        )
        if primary is None:
            raise ToolFailure(cleanup.kind, cleanup.sentence, cleanup.next_action) from cleanup
        # Raised from the `finally`, so this replaces the primary failure with the same kind
        # and its own text plus the cleanup's: one failure the operator can act on.
        raise ToolFailure(
            primary.kind,
            f"{primary.message} {cleanup.sentence}",
            f"{primary.next_action} {cleanup.next_action}",
        ) from primary


def delete_and_verify(medialive: Any, identifier: str) -> None:
    """The map is gone only when reading it is classified RESOURCE_NOT_FOUND (§8.3 step 4)."""
    try:
        call_aws_operation(medialive, "delete_signal_map", Identifier=identifier)
    except ToolFailure as failure:
        raise CleanupFailure(identifier, failure.kind) from failure
    try:
        read_signal_map(medialive, identifier)
    except ToolFailure as failure:
        if failure.kind is FailureKind.RESOURCE_NOT_FOUND:
            return
        raise CleanupFailure(identifier, failure.kind) from failure
    raise CleanupFailure(identifier, FailureKind.UNEXPECTED_FAILURE)
