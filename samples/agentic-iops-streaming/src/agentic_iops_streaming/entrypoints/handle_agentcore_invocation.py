"""AgentCore Runtime entrypoint of agentic-iops-streaming
(extend_agentic_iops_streaming.md §1): identify, parse, stream."""

import logging
import os
import sys
from collections.abc import Iterator
from functools import cache
from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from pydantic import ValidationError

from agentic_iops_streaming.bootstrap.apply_agentic_iops_tool_defaults import (
    apply_agentic_iops_tool_defaults,
)
from agentic_iops_streaming.bootstrap.create_agentic_iops import AgenticIops, create_agentic_iops
from agentic_iops_streaming.bootstrap.export_approval_signing_key import export_approval_signing_key
from agentic_iops_streaming.domain.agentic_iops_request import AgenticIopsRequest
from agentic_iops_streaming.domain.read_token_actor import read_token_actor
from agentic_iops_streaming.settings.runtime_settings import (
    AgenticIopsSettings,
    load_agentic_iops_settings,
)
from agentic_iops_streaming.workflows.run_agentic_iops_turn import stream_agentic_iops_turn
from media_ops_contracts.domain_pack import DomainPackError
from media_ops_contracts.parse_skill import SkillError
from media_ops_contracts.stream_event import STREAM_EVENT_ADAPTER, ErrorEvent, StreamEvent
from media_ops_contracts.tool_failure import FailureKind, ToolFailure

ACTOR_HEADER = "x-amzn-bedrock-agentcore-runtime-custom-actor-id"
LOCAL_ACTOR = "local-operator"
LOCAL_SESSION = "local-session"
LOGGER = logging.getLogger("agentic_iops_streaming")

app = BedrockAgentCoreApp()


@cache
def get_agentic_iops() -> AgenticIops:
    export_approval_signing_key(os.environ)
    apply_agentic_iops_tool_defaults(os.environ)
    return create_agentic_iops(load_agentic_iops_settings())


@app.entrypoint
def invoke(payload: dict[str, Any], context: Any) -> Iterator[dict[str, Any]]:
    """Each event is yielded as it happens; BedrockAgentCoreApp encodes each dict once."""
    session_id = context.session_id or LOCAL_SESSION
    for event in respond(payload, context, session_id):
        validated = STREAM_EVENT_ADAPTER.validate_python(event)
        yield STREAM_EVENT_ADAPTER.dump_python(validated, mode="json")


def respond(payload: dict[str, Any], context: Any, session_id: str) -> Iterator[StreamEvent]:
    try:
        iops = get_agentic_iops()
        caller = identify_caller(context, iops.settings)
        if caller is None:
            yield refusal_event(session_id, jwt_mode=bool(iops.settings.agentic_iops_jwt_issuer))
            return
        session_id, actor_id = caller
        try:
            request = AgenticIopsRequest.model_validate(payload)
        except ValidationError:
            yield failure_event(
                session_id, "Send exactly one of prompt or decision.", "Fix the request."
            )
            return
        yield from stream_agentic_iops_turn(iops, request, session_id=session_id, actor_id=actor_id)
    except Exception:  # boundary: log the cause, stream a safe message
        LOGGER.exception("agent turn failed", extra={"session.id": session_id})
        yield failure_event(
            session_id,
            "The agent could not finish this request.",
            "Retry, or check logs.",
            kind=FailureKind.UNEXPECTED_FAILURE,
        )


def identify_caller(context: Any, settings: AgenticIopsSettings) -> tuple[str, str] | None:
    """(session id, actor id). With JWT authorization the actor is the token's `sub` and the
    actor header is ignored; otherwise it is the header. Only local mode fills in a gap."""
    headers = {key.lower(): value for key, value in (context.request_headers or {}).items()}
    local = settings.agentic_iops_local_mode
    if settings.agentic_iops_jwt_issuer:
        actor_id = read_token_actor(
            headers.get("authorization"),
            issuer=settings.agentic_iops_jwt_issuer,
            allowed_clients=settings.jwt_allowed_clients,
        )
    else:
        actor_id = headers.get(ACTOR_HEADER) or (LOCAL_ACTOR if local else None)
    session_id = context.session_id or (LOCAL_SESSION if local else None)
    if actor_id is None or session_id is None:
        return None
    return session_id, actor_id


def refusal_event(session_id: str, *, jwt_mode: bool) -> ErrorEvent:
    if jwt_mode:
        return failure_event(
            session_id,
            "The request has no valid bearer token or no session.",
            "Send a current access token from this runtime's identity provider and a session id.",
        )
    return failure_event(
        session_id,
        "The request names no actor or session.",
        f"Send the {ACTOR_HEADER} header and a runtime session id.",
    )


def failure_event(
    session_id: str,
    message: str,
    next_action: str,
    *,
    kind: FailureKind = FailureKind.INVALID_REQUEST,
) -> ErrorEvent:
    return ErrorEvent(session_id=session_id, kind=kind, message=message, next_action=next_action)


STARTUP_ERRORS = (ValidationError, DomainPackError, SkillError, ToolFailure, RuntimeError)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        get_agentic_iops()  # a broken setting, pack or skill stops startup, not a request
    except STARTUP_ERRORS as error:
        print(
            f"agentic-iops-streaming cannot start: {describe_startup_error(error)}", file=sys.stderr
        )
        print(
            "Fix the root .env (see .env.example), then run `just run agentic-iops-streaming` "
            "again.",
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    app.run()


def describe_startup_error(error: Exception) -> str:
    """One line, without values: a settings error lists its fields and reasons only."""
    if isinstance(error, ValidationError):
        return "; ".join(
            f"{'.'.join(map(str, e['loc'])) or 'settings'}: {e['msg']}" for e in error.errors()
        )
    if isinstance(error, ToolFailure):
        return f"{error.message} {error.next_action}"
    return str(error)


if __name__ == "__main__":
    main()
