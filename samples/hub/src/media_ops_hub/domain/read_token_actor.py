"""The actor of a JWT-authorized request: the `sub` of the bearer token (extend_the_hub.md §1).

With inbound JWT authorization, AgentCore Runtime verifies the token's signature, issuer,
expiry and client before the request reaches the container, and forwards the Authorization
header only because the stack allowlists it. A runtime accepts either IAM or JWT callers,
never both, so every request that carries the header here was verified.

The hub does not verify the signature again. It re-checks the claims it relies on (issuer,
client, expiry, subject), so a container whose settings disagree with the stack's authorizer
fails closed. HUB_JWT_ISSUER is therefore set only by the CDK on a JWT-authorized runtime,
and startup refuses it together with HUB_LOCAL_MODE.
"""

import time
from collections.abc import Set
from typing import Any

import jwt


def read_token_actor(
    authorization: str | None,
    *,
    issuer: str,
    allowed_clients: Set[str],
    now: float | None = None,
) -> str | None:
    """The token's `sub`, or None when the header or any checked claim is missing or wrong."""
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
