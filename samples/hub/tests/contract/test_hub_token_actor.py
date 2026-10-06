"""With inbound JWT authorization the actor is the token's `sub` (extend_the_hub.md §1)."""

import time
from types import SimpleNamespace

import jwt
import pytest
from hub_test_setup import build_hub
from pydantic import ValidationError
from scripted_model import ScriptedModel, call, say

from media_ops_contracts.stream_event import STREAM_EVENT_ADAPTER
from media_ops_hub.domain.read_token_actor import read_token_actor
from media_ops_hub.entrypoints import handle_agentcore_invocation as entrypoint
from media_ops_hub.settings.runtime_settings import HubSettings

ISSUER = "https://cognito-idp.us-west-2.amazonaws.com/us-west-2_EXAMPLE"
CLIENT = "example-client-id"
ACTOR_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actor-Id"
NOW = 1_800_000_000.0


def token(**overrides):
    """A Cognito-style access token. The key is irrelevant: AgentCore verified the signature."""
    claims = {"sub": "alice", "iss": ISSUER, "client_id": CLIENT, "exp": NOW + 600}
    claims.update(overrides)
    claims = {name: value for name, value in claims.items() if value is not None}
    return "Bearer " + jwt.encode(claims, "test-only-key-not-a-secret-32-bytes", algorithm="HS256")


def actor_of(authorization):
    return read_token_actor(authorization, issuer=ISSUER, allowed_clients={CLIENT}, now=NOW)


def test_a_verified_token_names_its_subject_as_the_actor():
    assert actor_of(token()) == "alice"
    assert actor_of(token().replace("Bearer", "bearer")) == "alice"


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "",
        "Bearer ",
        "Basic YWxpY2U6c2VjcmV0",
        "Bearer not-a-jwt",
        token(iss="https://issuer.example.com"),
        token(client_id="another-client"),
        token(client_id=None),
        token(exp=NOW - 1),
        token(exp=None),
        token(sub=None),
        token(sub=" "),
    ],
    ids=[
        "no-header", "empty", "no-token", "not-bearer", "malformed", "other-issuer",
        "other-client", "no-client", "expired", "no-expiry", "no-subject", "blank-subject",
    ],
)  # fmt: skip
def test_any_missing_or_mismatched_claim_names_no_actor(authorization):
    assert actor_of(authorization) is None


def jwt_hub(tmp_path, model):
    return build_hub(tmp_path, model, jwt_issuer=ISSUER, jwt_clients=CLIENT)


def invoke(payload, headers, session="session-a"):
    context = SimpleNamespace(session_id=session, request_headers=headers)
    return [
        STREAM_EVENT_ADAPTER.validate_python(item) for item in entrypoint.invoke(payload, context)
    ]


def fresh_token(sub):
    return token(sub=sub, exp=time.time() + 600)


def test_jwt_mode_ignores_the_actor_header(tmp_path, monkeypatch):
    model = ScriptedModel([say("never sent")])
    monkeypatch.setattr(entrypoint, "get_hub", lambda: jwt_hub(tmp_path, model).hub)

    [error] = invoke({"prompt": "Status?"}, {ACTOR_HEADER: "alice"})

    assert error.kind == "InvalidRequest"
    assert "bearer token" in error.message
    assert model.messages == []


def test_an_approval_belongs_to_the_token_subject_not_the_header(tmp_path, monkeypatch):
    model = ScriptedModel([call("stop_channel", "use-1", channel_id="ch-1")], [say("Stopped.")])
    hub = jwt_hub(tmp_path, model)
    monkeypatch.setattr(entrypoint, "get_hub", lambda: hub.hub)
    alice = {"Authorization": fresh_token("alice"), ACTOR_HEADER: "bob"}
    [*_, approval] = invoke({"prompt": "Stop ch-1."}, alice)
    decision = {"decision": {"approval_id": approval.approval_id, "approve": True}}

    bob_claiming_alice = {"Authorization": fresh_token("bob"), ACTOR_HEADER: "alice"}
    refused = invoke(decision, bob_claiming_alice)

    assert [event.type for event in refused] == ["error"]
    assert hub.pack.approvals == []
    invoke(decision, {"Authorization": fresh_token("alice")})
    assert len(hub.pack.approvals) == 1


def test_jwt_settings_must_be_complete_and_never_local():
    with pytest.raises(ValidationError, match="HUB_JWT_ALLOWED_CLIENTS"):
        HubSettings(hub_jwt_issuer=ISSUER)
    with pytest.raises(ValidationError, match="HUB_LOCAL_MODE"):
        HubSettings(hub_jwt_issuer=ISSUER, hub_jwt_allowed_clients=CLIENT, hub_local_mode=True)

    settings = HubSettings(hub_jwt_issuer=ISSUER, hub_jwt_allowed_clients=f" {CLIENT}, other ,")
    assert settings.jwt_allowed_clients == {CLIENT, "other"}
