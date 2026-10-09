"""Ask the human at the MCP client to type the exact resource id before a write.

The question goes out as an MCP form elicitation, so the answer comes from the client, never
from the model's tool arguments. A client that can't show a form can't write.

The trust boundary: the server can check only that the client returned the exact id, not
that a person typed it. This assumes a trusted client that shows the question to a human
and does not answer it by itself; an auto-answering client defeats it. Keep ALLOW_WRITES off
unless you trust the client.
"""

from fastmcp import Context
from mcp.types import ClientCapabilities

from media_ops_contracts.tool_failure import FailureKind, ToolFailure


def supports_form_elicitation(capabilities: ClientCapabilities | None) -> bool:
    """Form mode declared, or an elicitation capability naming no mode (the spec's original,
    form-only shape). A URL-only client can't show this question."""
    elicitation = capabilities.elicitation if capabilities else None
    if elicitation is None:
        return False
    return elicitation.form is not None or elicitation.url is None


async def confirm_with_operator(
    ctx: Context, *, action: str, resource_label: str, resource_id: str, parameters: dict
) -> None:
    """Return only if the client's user typed `resource_id` exactly; raise ToolFailure otherwise."""
    client = ctx.session.client_params  # None only before the client initialized
    if not supports_form_elicitation(client.capabilities if client else None):
        raise ToolFailure(
            FailureKind.APPROVAL_REQUIRED,
            f"{action} needs the operator to type the exact {resource_label}, and this MCP "
            "client can't ask: it doesn't support MCP form elicitation.",
            "Use an MCP client that supports elicitation, or make the change outside the agent.",
        )
    details = "\n".join(f"  {name}: {value}" for name, value in parameters.items())
    try:
        answer = await ctx.elicit(
            f"Approve {action} on {resource_label} {resource_id}?\n"
            f"Parameters:\n{details or '  (none)'}\n"
            f"Type the exact {resource_label} to approve it, or decline.",
            # fastmcp 3.4 splits elicit's overloads with string literals, so mypy sees only
            # the response_type=None one; str is a supported scalar (the tests answer through it).
            response_type=str,  # type: ignore[arg-type]
        )
    except Exception as error:
        # A client that declared elicitation but failed to ask: refuse, without its details.
        raise ToolFailure(
            FailureKind.APPROVAL_REQUIRED,
            f"The MCP client couldn't ask the operator to approve {action}; nothing changed.",
            "Use an MCP client that shows the question to a person, or make the change "
            "outside the agent.",
        ) from error
    if answer.action != "accept":
        raise ToolFailure(
            FailureKind.APPROVAL_REQUIRED,
            f"The operator did not approve {action} on {resource_id}.",
            "Nothing changed. Propose it again only if the operator asks.",
        )
    if answer.data != resource_id:
        raise ToolFailure(
            FailureKind.APPROVAL_REQUIRED,
            f"The {resource_label} the operator typed does not match {resource_id}.",
            f"Nothing changed. Call {action} again; the operator must type the exact "
            f"{resource_label}.",
        )
