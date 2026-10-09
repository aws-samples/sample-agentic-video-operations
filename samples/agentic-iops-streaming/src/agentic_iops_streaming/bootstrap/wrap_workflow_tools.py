"""Make the coordinator's workflow tools Strands tools, and keep the session's proposals (§8.1).

The same rule as the pack wrapper: an input the model must never supply is absent from the tool
schema and injected here. For the workflow tools that is `approved_action` (the §4 hook writes
it into the tool input) and `proposals` (read from this session's `agent.state`). A proposal
returned by discovery is written back to that state, so the save in a later request — possibly
in another container — stores the chain the operator actually saw.
"""

import inspect
from typing import Any

from strands import tool
from strands.types.tools import AgentTool, ToolContext

from agentic_iops_streaming.bootstrap.create_workflow_tools import WorkflowTools
from agentic_iops_streaming.bootstrap.wrap_pack_tools import report_failure, run_pack_function
from agentic_iops_streaming.domain.workflow_proposal_state import (
    read_workflow_proposals,
    write_workflow_proposal,
)
from agentic_iops_streaming.domain.workflow_records import WorkflowProposal
from media_ops_contracts.approved_action import ApprovedAction
from media_ops_contracts.domain_pack import ReadTool, WriteTool
from media_ops_contracts.tool_failure import FailureKind, ToolFailure

INJECTED = ("approved_action", "proposals")


def wrap_workflow_tools(workflow_tools: WorkflowTools) -> list[AgentTool]:
    """Strands tools for the coordinator's own surface, in a stable order."""
    return [wrap_read(function) for function in workflow_tools.reads] + [
        wrap_write(write) for write in workflow_tools.writes
    ]


def wrap_read(function: ReadTool) -> AgentTool:
    """A read tool. Discovery's proposal is kept in the session on its way back."""

    def read(*args: Any, tool_context: ToolContext, **kwargs: Any) -> Any:
        answer = run_pack_function(function, *args, **kwargs)
        if isinstance(answer, WorkflowProposal):
            write_workflow_proposal(tool_context.agent.state, answer)
        return answer

    describe_like(read, function)
    return tool(read, context=True)  # type: ignore[call-overload]  # strands' tool() overloads don't cover a (*args, tool_context, **kwargs) wrapper


def wrap_write(write: WriteTool) -> AgentTool:
    """The approved write: the signed approval and the session's proposals are injected."""
    function = write.function

    def guarded(*args: Any, tool_context: ToolContext, **kwargs: Any) -> Any:
        approval = tool_context.tool_use["input"].get("approved_action")
        if approval is None:  # only the approval hook sets it
            return report_failure(
                ToolFailure(
                    FailureKind.APPROVAL_REQUIRED,
                    "This write has no operator approval.",
                    "Propose the action and wait for the operator's decision.",
                )
            )
        return run_pack_function(
            function,
            *args,
            **kwargs,
            approved_action=ApprovedAction.model_validate(approval),
            proposals=read_workflow_proposals(tool_context.agent.state),
        )

    describe_like(guarded, function)
    return tool(guarded, context=True)  # type: ignore[call-overload]  # strands' tool() overloads don't cover a (*args, tool_context, **kwargs) wrapper


def describe_like(wrapper: Any, function: Any) -> None:
    """Give the wrapper the function's name, doc and schema, minus the injected inputs."""
    signature = inspect.signature(function)
    visible = [
        parameter for name, parameter in signature.parameters.items() if name not in INJECTED
    ]
    context = inspect.Parameter(
        "tool_context", inspect.Parameter.KEYWORD_ONLY, annotation=ToolContext
    )
    wrapper.__name__ = function.__name__
    wrapper.__doc__ = function.__doc__
    wrapper.__signature__ = signature.replace(parameters=[*visible, context])
    wrapper.__annotations__ = {
        name: hint for name, hint in function.__annotations__.items() if name not in INJECTED
    } | {"tool_context": ToolContext}
