"""What every approved write returns: the state before, after, and whether it was verified."""

from pydantic import BaseModel


class ActionResult(BaseModel):
    approval_id: str
    action: str
    resource_id: str
    before_state: str
    after_state: str
    verified: bool
