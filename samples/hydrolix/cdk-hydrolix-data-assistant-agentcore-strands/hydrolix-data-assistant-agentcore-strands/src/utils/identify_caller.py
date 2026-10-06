"""Who is asking, and which conversation they may use (RB9).

JWT mode (HYDROLIX_JWT_ISSUER, set by the CDK): AgentCore Runtime accepts only bearer
tokens from the configured Cognito user pool and app clients. It verifies their signature,
issuer, expiry and client, and forwards only the Authorization header. The actor is the
token's `sub`; a `user_id` or `session_id` in the payload is ignored. read_token_actor
(agentic-iops-streaming's rule) re-checks the claims it relies on, so a container whose settings
disagree with the stack's authorizer fails closed. The signature is AgentCore's to verify: only the
CDK sets HYDROLIX_JWT_ISSUER, and only on a runtime with that authorizer in front.

IAM mode (the default): any IAM principal allowed to invoke is a caller, and nothing names
who they are. There is no actor, so memory is off: no history is read or written.

The conversation is the AgentCore runtime session (context.session_id), never a payload
field. A runtime session is pinned to one microVM, so this process serves one session; the
first verified `sub` it sees owns it, and a request with another `sub` (someone who learned
the session id) is refused. Memory is keyed by (actor, session) as well, so even after the
microVM is recycled a reused session id only reaches its own actor's history.
"""

import time
from collections.abc import Mapping, Set
from dataclasses import dataclass
from threading import Lock
from typing import Any

import jwt

from src.settings.runtime_settings import RuntimeSettings


class CallerRefused(Exception):
    """The request names no usable identity or session; nothing runs."""


@dataclass(frozen=True)
class Caller:
    session_id: str
    actor_id: str | None  # None in IAM mode: no verified identity, so memory is off

    @property
    def memory_enabled(self) -> bool:
        return self.actor_id is not None


class ContainerOwner:
    """The one actor this process serves; the first verified one claims it."""

    def __init__(self) -> None:
        self._actor: str | None = None
        self._lock = Lock()

    def claim(self, actor_id: str) -> bool:
        with self._lock:
            if self._actor is None:
                self._actor = actor_id
            return self._actor == actor_id


CONTAINER_OWNER = ContainerOwner()


def read_token_actor(
    authorization: str | None,
    *,
    issuer: str,
    allowed_clients: Set[str],
    now: float | None = None,
) -> str | None:
    """The bearer token's `sub`, or None when the header or any checked claim is wrong."""
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    try:
        claims: dict[str, Any] = jwt.decode(token.strip(), options={"verify_signature": False})
    except jwt.InvalidTokenError:
        return None
    expires = claims.get("exp")
    subject = claims.get("sub")
    if (
        claims.get("iss") != issuer
        or claims.get("client_id") not in allowed_clients
        or not isinstance(expires, int | float)
        or expires <= (time.time() if now is None else now)
        or not isinstance(subject, str)
        or not subject.strip()
    ):
        return None
    return subject


def identify_caller(
    session_id: str | None,
    headers: Mapping[str, str] | None,
    settings: RuntimeSettings,
    owner: ContainerOwner | None = None,
) -> Caller:
    if not session_id:
        raise CallerRefused("The request has no runtime session id.")
    if not settings.hydrolix_jwt_issuer:
        return Caller(session_id=session_id, actor_id=None)
    lowered = {name.lower(): value for name, value in (headers or {}).items()}
    actor_id = read_token_actor(
        lowered.get("authorization"),
        issuer=settings.hydrolix_jwt_issuer,
        allowed_clients=settings.jwt_allowed_clients,
    )
    if actor_id is None:
        raise CallerRefused("The request has no valid access token from this app's sign-in.")
    if not (owner or CONTAINER_OWNER).claim(actor_id):
        raise CallerRefused("This session belongs to another user. Start a new session.")
    return Caller(session_id=session_id, actor_id=actor_id)
