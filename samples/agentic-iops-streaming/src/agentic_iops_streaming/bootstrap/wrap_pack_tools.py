"""Turn domain-pack functions into Strands tools (extend_agentic_iops_streaming.md §2, §4).

Packs stay framework-free; only the coordinator imports Strands. A write tool's schema omits
`approved_action`, so the model can never supply it: the approval hook writes the signed
approval into the tool input, and the wrapper hands it to the pack function.
"""

import functools
import inspect
import json
from dataclasses import dataclass
from typing import Any

from strands import tool
from strands.types.tools import AgentTool, ToolContext

from media_ops_contracts.approved_action import ApprovedAction
from media_ops_contracts.domain_pack import DomainPack, DomainPackError, ReadTool, WriteTool
from media_ops_contracts.tool_failure import FailureKind, ToolFailure


@dataclass(frozen=True)
class ToolSurface:
    tools: list[AgentTool]
    pack_by_tool: dict[str, str]  # tool name -> pack name
    writes: dict[str, WriteTool]  # registered write tools only


def wrap_pack_tools(packs: list[DomainPack], *, allow_writes: bool) -> ToolSurface:
    tools: list[AgentTool] = []
    pack_by_tool: dict[str, str] = {}
    writes: dict[str, WriteTool] = {}
    for pack in packs:
        for function in pack.read_tools():
            claim_tool_name(pack_by_tool, function.__name__, pack.name)
            tools.append(wrap_read_tool(function))
        for write in pack.write_tools() if allow_writes else []:
            claim_tool_name(pack_by_tool, write.function.__name__, pack.name)
            tools.append(wrap_write_tool(write))
            writes[write.function.__name__] = write
    return ToolSurface(tools=tools, pack_by_tool=pack_by_tool, writes=writes)


def claim_tool_name(pack_by_tool: dict[str, str], name: str, pack: str) -> None:
    """Tool names are global to the agent: two packs offering the same name stop startup."""
    owner = pack_by_tool.setdefault(name, pack)
    if owner != pack or name == "load_skill":
        raise DomainPackError(f"Tool name {name!r} is offered by both {owner} and {pack}.")


def wrap_read_tool(function: ReadTool) -> AgentTool:
    @functools.wraps(function)
    def read(*args: Any, **kwargs: Any) -> Any:
        return run_pack_function(function, *args, **kwargs)

    return tool(read)


def wrap_write_tool(write: WriteTool) -> AgentTool:
    function = write.function
    signature = inspect.signature(function)
    visible = [p for name, p in signature.parameters.items() if name != "approved_action"]
    context = inspect.Parameter(
        "tool_context", inspect.Parameter.KEYWORD_ONLY, annotation=ToolContext
    )

    def guarded(*args: Any, tool_context: ToolContext, **kwargs: Any) -> Any:
        approval = tool_context.tool_use["input"].get("approved_action")
        if approval is None:  # only the approval hook sets it
            failure = ToolFailure(
                FailureKind.APPROVAL_REQUIRED,
                "This write has no operator approval.",
                "Propose the action and wait for the operator's decision.",
            )
            return report_failure(failure)
        approved = ApprovedAction.model_validate(approval)
        return run_pack_function(function, *args, **kwargs, approved_action=approved)

    guarded.__name__ = function.__name__
    guarded.__doc__ = function.__doc__
    guarded.__signature__ = signature.replace(parameters=[*visible, context])
    guarded.__annotations__ = {
        name: hint for name, hint in function.__annotations__.items() if name != "approved_action"
    } | {"tool_context": ToolContext}
    return tool(guarded, context=True)


def run_pack_function(function: Any, *args: Any, **kwargs: Any) -> Any:
    """Call a pack function; a ToolFailure becomes an error result with a next action."""
    try:
        result = function(*args, **kwargs)
    except ToolFailure as failure:
        return report_failure(failure)
    if isinstance(result, list):
        return [item.model_dump(mode="json") for item in result]
    return result


def report_failure(failure: ToolFailure) -> dict[str, Any]:
    text = json.dumps(
        {"error": failure.kind, "message": failure.message, "next_action": failure.next_action}
    )
    return {"status": "error", "content": [{"text": text}]}
