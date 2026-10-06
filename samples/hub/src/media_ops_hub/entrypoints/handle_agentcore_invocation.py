"""AgentCore Runtime entrypoint of the hub (extend_the_hub.md §1): identify, parse, stream."""

import logging
import os
import sys
from collections.abc import Iterator
from functools import cache
from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from pydantic import ValidationError

from media_ops_contracts.domain_pack import DomainPackError
from media_ops_contracts.parse_skill import SkillError
from media_ops_contracts.stream_event import STREAM_EVENT_ADAPTER, ErrorEvent, StreamEvent
from media_ops_contracts.tool_failure import FailureKind, ToolFailure
from media_ops_hub.bootstrap.create_hub import Hub, create_hub
from media_ops_hub.bootstrap.export_approval_signing_key import export_approval_signing_key
from media_ops_hub.domain.hub_request import HubRequest
from media_ops_hub.settings.runtime_settings import load_hub_settings
from media_ops_hub.workflows.run_hub_turn import stream_hub_turn

ACTOR_HEADER = "x-amzn-bedrock-agentcore-runtime-custom-actor-id"
LOCAL_ACTOR = "local-operator"
LOCAL_SESSION = "local-session"
LOGGER = logging.getLogger("media_ops_hub")

app = BedrockAgentCoreApp()


@cache
def get_hub() -> Hub:
    export_approval_signing_key(os.environ)
    return create_hub(load_hub_settings())


@app.entrypoint
def invoke(payload: dict[str, Any], context: Any) -> Iterator[dict[str, Any]]:
    """Each event is yielded as it happens; BedrockAgentCoreApp encodes each dict once."""
    session_id = context.session_id or LOCAL_SESSION
    for event in respond(payload, context, session_id):
        validated = STREAM_EVENT_ADAPTER.validate_python(event)
        yield STREAM_EVENT_ADAPTER.dump_python(validated, mode="json")


def respond(payload: dict[str, Any], context: Any, session_id: str) -> Iterator[StreamEvent]:
    try:
        hub = get_hub()
        caller = identify_caller(context, local_mode=hub.settings.hub_local_mode)
        if caller is None:
            yield failure_event(
                session_id,
                "The request names no actor or session.",
                f"Send the {ACTOR_HEADER} header and a runtime session id.",
            )
            return
        session_id, actor_id = caller
        try:
            request = HubRequest.model_validate(payload)
        except ValidationError:
            yield failure_event(
                session_id, "Send exactly one of prompt or decision.", "Fix the request."
            )
            return
        yield from stream_hub_turn(hub, request, session_id=session_id, actor_id=actor_id)
    except Exception:  # boundary: log the cause, stream a safe message
        LOGGER.exception("hub turn failed", extra={"session.id": session_id})
        yield failure_event(
            session_id,
            "The hub could not finish this request.",
            "Retry, or check logs.",
            kind=FailureKind.UNEXPECTED_FAILURE,
        )


def identify_caller(context: Any, *, local_mode: bool) -> tuple[str, str] | None:
    """(session id, actor id). Only local mode may fill in a missing one."""
    headers = {key.lower(): value for key, value in (context.request_headers or {}).items()}
    actor_id = headers.get(ACTOR_HEADER) or (LOCAL_ACTOR if local_mode else None)
    session_id = context.session_id or (LOCAL_SESSION if local_mode else None)
    if actor_id is None or session_id is None:
        return None
    return session_id, actor_id


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
        get_hub()  # a broken setting, pack or skill stops startup, not a request
    except STARTUP_ERRORS as error:
        print(f"media-ops-hub cannot start: {describe_startup_error(error)}", file=sys.stderr)
        print(
            "Fix the root .env (see .env.example), then run `just run hub` again.", file=sys.stderr
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
