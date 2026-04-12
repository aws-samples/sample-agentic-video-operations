"""
SessionPool — maintains a pool of pre-warmed Code Interpreter sessions.

Eliminates the 1-2s cold-start latency on code_mode invocations by reusing
sessions across calls. Falls back gracefully if sessions become unhealthy
or expire past their TTL.
"""

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from bedrock_agentcore.tools.code_interpreter_client import CodeInterpreter

logger = logging.getLogger(__name__)


class SessionPoolError(Exception):
    """Raised when the pool cannot acquire a session."""


@dataclass
class PooledSession:
    """Tracks a Code Interpreter session in the pool."""

    client: CodeInterpreter
    created_at: float  # time.monotonic() when session was started
    last_used_at: float  # time.monotonic() when last released back to pool
    use_count: int = 0

    def is_expired(self, ttl_seconds: int) -> bool:
        """Check if session has exceeded its TTL since last use."""
        return (time.monotonic() - self.last_used_at) > ttl_seconds


class SessionPool:
    """Pool of pre-warmed Code Interpreter sessions.

    Args:
        max_size: Maximum number of sessions in the pool. Default 2.
        ttl_seconds: Time-to-live for idle sessions. Default 300s (5 min).
        region: AWS region for Code Interpreter. Defaults to AWS_REGION env var.
        acquire_timeout: Max seconds to wait for a session. Default 10s.
    """

    def __init__(
        self,
        max_size: int = 2,
        ttl_seconds: int = 300,
        region: Optional[str] = None,
        acquire_timeout: float = 10.0,
    ) -> None:
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.region = region or os.environ.get("AWS_REGION", "us-west-2")
        self.acquire_timeout = acquire_timeout

        self._available: list[PooledSession] = []
        self._in_use: set[int] = set()  # id(PooledSession) for tracking
        self._lock = threading.Lock()
        self._release_event = threading.Event()

        # Pre-warm 1 session at init
        self._pre_warm(count=1)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    # Only health-check sessions idle longer than this threshold (seconds)
    IDLE_HEALTH_CHECK_THRESHOLD = 120

    def acquire(self) -> "PooledSession":
        """Get a session from the pool.

        Returns a pre-warmed session if available, otherwise creates a new one
        (up to max_size). Blocks briefly if the pool is at capacity.

        Raises:
            SessionPoolError: If unable to acquire a session after timeout.
        """
        deadline = time.monotonic() + self.acquire_timeout

        while True:
            with self._lock:
                # Try to grab an available session, discarding expired ones
                while self._available:
                    pooled = self._available.pop(0)
                    if pooled.is_expired(self.ttl_seconds):
                        self._stop_session_safe(pooled)
                        continue
                    # Health-check only if idle for a long time
                    idle_time = time.monotonic() - pooled.last_used_at
                    if idle_time > self.IDLE_HEALTH_CHECK_THRESHOLD and not self._is_healthy(pooled):
                        self._stop_session_safe(pooled)
                        continue
                    # Got a valid session
                    pooled.use_count += 1
                    self._in_use.add(id(pooled))
                    return pooled

                # No available session — can we create a new one?
                if self._active_count_unlocked() < self.max_size:
                    pooled = self._create_session()
                    if pooled is not None:
                        pooled.use_count += 1
                        self._in_use.add(id(pooled))
                        return pooled

            # Pool is at capacity and nothing available — wait for a release
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SessionPoolError(
                    f"Timed out waiting for a session (max_size={self.max_size})"
                )
            self._release_event.clear()
            self._release_event.wait(timeout=min(remaining, 1.0))

    def release(self, session: "PooledSession") -> None:
        """Return a session to the pool for reuse.

        Expired sessions are discarded and a replacement is pre-warmed.
        Health checks are deferred to acquire() to avoid round-trip
        latency on every release.
        """
        with self._lock:
            self._in_use.discard(id(session))

            if session.is_expired(self.ttl_seconds):
                self._stop_session_safe(session)
                if self._active_count_unlocked() < self.max_size:
                    self._pre_warm_unlocked(count=1)
            else:
                session.last_used_at = time.monotonic()
                self._available.append(session)

        # Signal any threads waiting in acquire()
        self._release_event.set()

    def shutdown(self) -> None:
        """Stop all sessions in the pool. Called on container shutdown."""
        with self._lock:
            for pooled in self._available:
                self._stop_session_safe(pooled)
            self._available.clear()
            self._in_use.clear()
            logger.info("SessionPool shut down — all sessions stopped")

    # ------------------------------------------------------------------
    # Pool introspection
    # ------------------------------------------------------------------

    def active_count(self) -> int:
        """Total active sessions (in-use + available). Thread-safe."""
        with self._lock:
            return self._active_count_unlocked()

    def _active_count_unlocked(self) -> int:
        """Total active sessions — caller must hold self._lock."""
        return len(self._available) + len(self._in_use)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _pre_warm(self, count: int = 1) -> None:
        """Start sessions and add them to the available pool."""
        with self._lock:
            self._pre_warm_unlocked(count)

    def _pre_warm_unlocked(self, count: int = 1) -> None:
        """Pre-warm without acquiring the lock — caller must hold self._lock."""
        for _ in range(count):
            if self._active_count_unlocked() >= self.max_size:
                break
            pooled = self._create_session()
            if pooled is not None:
                self._available.append(pooled)

    def _create_session(self) -> Optional["PooledSession"]:
        """Create and start a new Code Interpreter session.

        Returns None if session creation fails (caller should handle fallback).
        """
        client = CodeInterpreter(self.region)
        try:
            client.start()
            now = time.monotonic()
            logger.info("SessionPool: new session started (region=%s)", self.region)
            return PooledSession(
                client=client,
                created_at=now,
                last_used_at=now,
            )
        except Exception as exc:
            logger.error("SessionPool: failed to start session: %s", exc)
            return None

    def _is_healthy(self, session: "PooledSession") -> bool:
        """Check if a session is still usable by running a trivial script."""
        try:
            response = session.client.invoke(
                "executeCode",
                {"language": "python", "code": "print('ok')"},
            )
            # Check the stream for a successful text output
            for event in response.get("stream", []):
                result = event.get("result", {})
                if result.get("status") == "error" or result.get("isError"):
                    return False
                for item in result.get("content", []):
                    if item.get("type") == "text" and "ok" in item.get("text", ""):
                        return True
            return False
        except Exception as exc:
            logger.warning("SessionPool: health check failed: %s", exc)
            return False

    def _is_expired(self, session: "PooledSession") -> bool:
        """Check if a session has exceeded its TTL."""
        return session.is_expired(self.ttl_seconds)

    @staticmethod
    def _stop_session_safe(session: "PooledSession") -> None:
        """Stop a session, swallowing any errors."""
        try:
            session.client.stop()
        except Exception as exc:
            logger.warning("SessionPool: failed to stop session: %s", exc)
