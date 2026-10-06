"""What every approved write needs: an approval check and a bounded verification (§9)."""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class ApprovalCheck:
    signing_key: bytes
    now: datetime


@dataclass(frozen=True)
class VerificationPolicy:
    deadline_seconds: float = 120.0
    interval_seconds: float = 5.0
    sleep: Callable[[float], None] = field(default=time.sleep)
    monotonic: Callable[[], float] = field(default=time.monotonic)


def wait_for_condition[T](
    read: Callable[[], T], is_done: Callable[[T], bool], policy: VerificationPolicy
) -> T:
    """Poll `read` until `is_done` or the deadline passes; return the last observation."""
    deadline = policy.monotonic() + policy.deadline_seconds
    observed = read()
    while not is_done(observed) and policy.monotonic() < deadline:
        policy.sleep(policy.interval_seconds)
        observed = read()
    return observed
