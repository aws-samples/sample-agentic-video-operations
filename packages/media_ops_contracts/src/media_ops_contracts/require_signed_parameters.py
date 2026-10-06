"""Reject a write whose inputs differ from the ones the operator signed (write_safe_tools.md §3).

`require_action_approval` proves who approved which action on which resource, and when. It does
not look at `parameters`, because only the write knows its own inputs. So every write also calls
this with the inputs it is about to act on.
"""

from collections.abc import Mapping

from media_ops_contracts.approved_action import ApprovedAction
from media_ops_contracts.tool_failure import FailureKind, ToolFailure


def require_signed_parameters(
    approved_action: ApprovedAction, expected: Mapping[str, object]
) -> None:
    """Raise ToolFailure unless the signed parameters are exactly `expected`.

    `expected` is compared as the approval hook recorded it: values as `str`, `None` left out.
    A write with no inputs beyond its resource passes `{}`.
    """
    wanted = {name: str(value) for name, value in expected.items() if value is not None}
    signed = approved_action.parameters
    differing = sorted(
        name for name in signed.keys() | wanted.keys() if signed.get(name) != wanted.get(name)
    )
    if differing:
        raise ToolFailure(
            FailureKind.APPROVAL_REQUIRED,
            f"The approval was signed for other inputs: {', '.join(differing)}.",
            "Propose the action again with these inputs and ask the operator to approve it.",
        )
