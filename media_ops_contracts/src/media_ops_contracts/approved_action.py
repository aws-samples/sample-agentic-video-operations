"""Approval objects bound to one exact action (tool-contract §3)."""

import hashlib
import hmac
import json
from datetime import timedelta

from pydantic import AwareDatetime, BaseModel, ConfigDict

APPROVAL_LIFETIME = timedelta(minutes=10)


class ActionProposal(BaseModel):
    """A write the operator is asked to approve."""

    model_config = ConfigDict(frozen=True)

    actor_id: str
    action: str
    resource_id: str
    parameters: dict[str, str] = {}


class ApprovedAction(ActionProposal):
    """A proposal the operator approved, signed so specialists can verify it."""

    approval_id: str
    expires_at: AwareDatetime
    signature: str


def sign_approved_action(
    proposal: ActionProposal,
    *,
    approval_id: str,
    expires_at: AwareDatetime,
    signing_key: bytes,
) -> ApprovedAction:
    """Bind an approval to the exact proposal and sign it."""
    draft = ApprovedAction(
        **proposal.model_dump(), approval_id=approval_id, expires_at=expires_at, signature=""
    )
    signature = compute_approval_signature(draft.model_dump(mode="json"), signing_key)
    return draft.model_copy(update={"signature": signature})


def compute_approval_signature(fields: dict, signing_key: bytes) -> str:
    """HMAC-SHA256 over the canonical JSON of every field except the signature.

    `fields` must come from `model_dump(mode="json")` so the signer and the verifier,
    which run in different runtimes, serialize datetimes identically.
    """
    payload = {key: value for key, value in fields.items() if key != "signature"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hmac.new(signing_key, canonical.encode(), hashlib.sha256).hexdigest()
