"""The exact write the operator is asked to approve, from the model's tool call."""

import inspect
from typing import Any

from media_ops_contracts.approved_action import ActionProposal
from media_ops_contracts.domain_pack import WriteTool


def propose_write_action(
    write: WriteTool, tool_input: dict[str, Any], *, actor_id: str
) -> ActionProposal:
    """Defaults are filled in, so the proposal equals what the pack function will check."""
    inputs = {name: value for name, value in tool_input.items() if name != "approved_action"}
    signature = inspect.signature(write.function)
    known = {name: value for name, value in inputs.items() if name in signature.parameters}
    bound = signature.bind_partial(**known)
    bound.apply_defaults()
    arguments = dict(bound.arguments)
    arguments.pop("approved_action", None)
    resource_id = arguments.pop(write.resource_parameter, "")
    return ActionProposal(
        actor_id=actor_id,
        action=write.function.__name__,
        resource_id=str(resource_id),
        parameters={name: str(value) for name, value in arguments.items() if value is not None},
    )
