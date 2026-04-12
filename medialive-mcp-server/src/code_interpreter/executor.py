"""
CodeInterpreterExecutor — wraps AgentCore Code Interpreter for sandboxed Python execution.

Supports two session strategies:
  1. Pooled — acquire a pre-warmed session from SessionPool, execute, release back.
  2. Per-request — start a fresh session, execute, stop (original behavior / fallback).

The Code Interpreter runs in a Firecracker microVM, providing OS-level isolation.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from bedrock_agentcore.tools.code_interpreter_client import CodeInterpreter

if TYPE_CHECKING:
    from .session_pool import SessionPool

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of a sandboxed script execution."""

    success: bool
    stdout: str
    stderr: Optional[str] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None


class CodeInterpreterExecutor:
    """Wraps AgentCore Code Interpreter for sandboxed Python execution.

    Each call to execute() starts a fresh session and tears it down in a finally
    block. This avoids session leaks and keeps the implementation stateless.

    Args:
        timeout: Maximum session timeout in seconds. Default 30s accounts for
                 session startup (~1-2s) plus script execution time.
        region:  AWS region for the Code Interpreter service.
                 Defaults to AWS_REGION env var or us-west-2.
    """

    def __init__(
        self,
        timeout: int = 30,
        region: Optional[str] = None,
        pool: SessionPool | None = None,
    ) -> None:
        self.timeout = timeout
        self.region = region or os.environ.get("AWS_REGION", "us-west-2")
        self._pool = pool

    def execute(self, data_json: str, script: str) -> ExecutionResult:
        """Execute a processing script against injected DATA in a Code Interpreter session.

        Routes to pooled or per-request session strategy based on pool availability.
        Falls back to per-request if the pool acquire fails.

        Args:
            data_json: JSON-serialized API response to inject as the DATA variable.
            script:    User-provided Python processing script.

        Returns:
            ExecutionResult with stdout, stderr, success flag, and error details.
        """
        if self._pool is not None:
            try:
                return self._execute_pooled(data_json, script)
            except Exception as exc:
                logger.warning(
                    "Pooled execution failed, falling back to per-request: %s", exc
                )
        return self._execute_per_request(data_json, script)

    # ------------------------------------------------------------------
    # Session strategies
    # ------------------------------------------------------------------

    def _execute_pooled(self, data_json: str, script: str) -> ExecutionResult:
        """Acquire session from pool, execute, release back.

        If the acquired session fails execution with a session-level error,
        the pool's release() will discard it and pre-warm a replacement.
        """
        from .session_pool import SessionPoolError

        pooled = self._pool.acquire()  # may raise SessionPoolError
        full_code = self._build_code(data_json, script)

        try:
            response = pooled.client.invoke(
                "executeCode",
                {"language": "python", "code": full_code},
            )
            return self._process_response(response, script)
        except Exception as exc:
            error_type = type(exc).__name__
            error_msg = str(exc)

            if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                return ExecutionResult(
                    success=False,
                    stdout="",
                    error_type="TimeoutError",
                    error_message=f"Script exceeded {self.timeout}s execution limit",
                )

            logger.error("Pooled invocation failed: %s: %s", error_type, error_msg)
            return ExecutionResult(
                success=False,
                stdout="",
                error_type=error_type,
                error_message=error_msg,
            )
        finally:
            self._pool.release(pooled)

    def _execute_per_request(self, data_json: str, script: str) -> ExecutionResult:
        """Original per-request lifecycle: start → execute → stop.

        Used as fallback when no pool is configured or pool acquire fails.
        """
        code_client = CodeInterpreter(self.region)
        full_code = self._build_code(data_json, script)

        try:
            code_client.start()
        except Exception as exc:
            logger.error("Failed to start Code Interpreter session: %s", exc)
            return ExecutionResult(
                success=False,
                stdout="",
                error_type="SessionError",
                error_message=f"Failed to start Code Interpreter session: {exc}",
            )

        try:
            response = code_client.invoke(
                "executeCode",
                {"language": "python", "code": full_code},
            )
            return self._process_response(response, script)

        except Exception as exc:
            error_type = type(exc).__name__
            error_msg = str(exc)

            # Detect timeout from exception message patterns
            if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                return ExecutionResult(
                    success=False,
                    stdout="",
                    error_type="TimeoutError",
                    error_message=f"Script exceeded {self.timeout}s execution limit",
                )

            logger.error("Code Interpreter invocation failed: %s: %s", error_type, error_msg)
            return ExecutionResult(
                success=False,
                stdout="",
                error_type=error_type,
                error_message=error_msg,
            )
        finally:
            try:
                code_client.stop()
            except Exception as stop_exc:
                logger.warning("Failed to stop Code Interpreter session: %s", stop_exc)

    def _build_code(self, data_json: str, script: str) -> str:
        """Build the full code string by prepending DATA assignment.

        Uses json.dumps to safely serialize the data as a Python literal,
        avoiding triple-quote escaping issues entirely.
        """
        return (
            "import json as _json\n"
            "\n"
            f"DATA = _json.dumps({data_json})\n"
            "\n"
            "# --- User script begins below ---\n"
            f"{script}"
        )

    def _process_response(self, response: dict, script: str) -> ExecutionResult:
        """Extract stdout/stderr from the Code Interpreter streaming response."""
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        error_type: Optional[str] = None
        error_message: Optional[str] = None

        stream = response.get("stream", [])
        for event in stream:
            result = event.get("result", {})
            content_items = result.get("content", [])

            for item in content_items:
                item_type = item.get("type", "")
                text = item.get("text", "")

                if item_type == "text":
                    stdout_parts.append(text)
                elif item_type == "error" or item_type == "stderr":
                    stderr_parts.append(text)

            # Check for execution errors in the result metadata
            if result.get("status") == "error" or result.get("isError"):
                error_type = result.get("errorType", "RuntimeError")
                error_message = result.get("errorMessage", "")
                # Also check content for error details
                for item in content_items:
                    if item.get("type") == "text" and not error_message:
                        error_message = item.get("text", "")

        stdout = "\n".join(stdout_parts) if stdout_parts else ""
        stderr = "\n".join(stderr_parts) if stderr_parts else None

        # Detect errors from stderr content when no explicit error status
        if not error_type and stderr:
            error_type, error_message = self._parse_stderr_error(stderr, script)

        if error_type:
            return ExecutionResult(
                success=False,
                stdout=stdout,
                stderr=stderr,
                error_type=error_type,
                error_message=error_message or "Unknown error",
            )

        return ExecutionResult(
            success=True,
            stdout=stdout,
            stderr=stderr,
        )

    @staticmethod
    def _parse_stderr_error(
        stderr: str, script: str
    ) -> tuple[Optional[str], Optional[str]]:
        """Try to extract error type and message from stderr output.

        Common patterns:
          SyntaxError: invalid syntax (<string>, line 3)
          NameError: name 'x' is not defined
          Traceback (most recent call last): ... RuntimeError: boom
        """
        lines = stderr.strip().splitlines()
        if not lines:
            return None, None

        last_line = lines[-1].strip()

        # Standard Python error format: "ErrorType: message"
        if "Error:" in last_line or "Exception:" in last_line:
            colon_idx = last_line.index(":")
            return last_line[:colon_idx].strip(), last_line[colon_idx + 1 :].strip()

        # Timeout patterns
        if "timeout" in last_line.lower():
            return "TimeoutError", last_line

        return None, None
