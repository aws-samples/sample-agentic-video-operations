# Agent Contract

How the AgentCore runtimes in `media-services-langchain` talk to callers and to each other. There are 3 runtimes:
- the coordinator,
- EML (the MediaLive specialist),
- EMX (the MediaConnect specialist).

The `medialive` Strands agent and the `hydrolix` agents SHOULD follow sections 1–2 when they are next changed.

Enforces guidelines §3–4 (layers, one-way dependencies), §7 (typed payloads), §9 (safety), §11 (prompts), §12 (observability), §13 (tests).

## 1. Runtime interface

All runtimes use `BedrockAgentCoreApp` on port 8080 (`/invocations`, `/ping`). Each runtime has one entrypoint file, `entrypoints/agentcore/handle_<role>_invocation.py`. That file only parses the request, calls the workflow and streams events.

**Coordinator request:**

```python
class CoordinatorRequest(BaseModel):
    prompt: str | None = None          # a new question
    decision: ApprovalDecision | None = None  # resumes a paused run
    # session_id comes from context.session_id (AgentCore requires at least 33 characters)
    # actor_id comes from the X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actor-Id header

class ApprovalDecision(BaseModel):
    approval_id: str
    approve: bool
    reason: str | None = None
```

**Specialist request.** Only the coordinator sends these:

```python
class SpecialistRequest(BaseModel):
    task: str                                   # a self-contained instruction
    approved_action: ApprovedAction | None = None   # present only for writes
```

**Response.** Every runtime streams `StreamEvent` objects. Each event is JSON-encoded exactly once:

```python
class StreamEventType(StrEnum):
    TASK_STARTED = "task_started"
    TOOL_CALLED = "tool_called"
    APPROVAL_REQUESTED = "approval_requested"
    ACTION_COMPLETED = "action_completed"
    VERIFICATION_COMPLETED = "verification_completed"
    FINAL_ANSWER = "final_answer"
    ERROR = "error"

class BaseStreamEvent(BaseModel):
    session_id: str
    at: AwareDatetime   # defaults to now, UTC

class TaskStarted(BaseStreamEvent):
    type: Literal[StreamEventType.TASK_STARTED] = StreamEventType.TASK_STARTED
    specialist: str
    task: str
# ... one class per type, fields as in the table below

StreamEvent = Annotated[TaskStarted | ToolCalled | ... | ErrorEvent, Field(discriminator="type")]
```

This is the same discriminated-union pattern as `sample-agentic-platform` (`core/models/streaming_models.py`). The fields are typed per event, and a client parses an event with one `TypeAdapter(StreamEvent)`.

| type | fields |
|---|---|
| `task_started` | `{specialist, task}` |
| `tool_called` | `{tool, read_only, resource_id?}`. No raw tool output |
| `approval_requested` | `{approval_id, proposal: ActionProposal, risk: "low"\|"high", expires_at}` |
| `action_completed` | `{approval_id, action, resource_id}` |
| `verification_completed` | `{approval_id, verified, before_state, after_state}` |
| `final_answer` | `{text}`. Impact first, then evidence, then the next action |
| `error` | `{kind, message, next_action}` from `ToolFailure` |

## 2. Memory and sessions

- **The LangGraph thread id is the session id.** One operator conversation is one thread.
- **Specialists use thread `"{session_id}:{specialist}"`.** They MUST NOT mint a random thread per delegation.
- **Isolation is by `actor_id`** through the existing `AgentCoreMemorySaver` namespace (`shared/memory.py`, which moves to `adapters/agentcore/`).
- **No memory when `MEMORY_ID` is empty.** This is the local and demo default: an in-memory checkpointer.

## 3. Specialists (EML, EMX)

- A specialist is `langchain.agents.create_agent(model, tools, system_prompt)`.
  - Its tools are the adapter functions from its MCP package (tool-contract.md).
  - Its prompt lives in `prompts/inspect_media_live_prompt.py` or `prompts/inspect_media_connect_prompt.py`.
- **Read tools are always available.** Write tools are only bound when the request carries an `approved_action`, and then only the one tool that matches `approved_action.action`.
- **The specialist verifies the signature, then executes, then verifies the resource state.** It never asks the model whether something is approved.
- **A specialist never imports the other specialist or the coordinator.**
- **Its endpoint is not exported from CDK.** IAM allows only the coordinator role to invoke it.

## 4. Coordinator

- The coordinator is `create_agent(model, tools, middleware=[HumanInTheLoopMiddleware(...)])`.
- **Specialists come from settings, not code:**

  ```python
  specialists: list[SpecialistConfig]   # name, runtime_arn, description, write_actions
  ```

  For each specialist the coordinator generates:
  - `ask_<name>(task)`: read-only, never interrupts.
  - `act_<name>(action, resource_id, parameters)`: interrupts first.

  Adding a specialist means adding a settings entry. There MUST NOT be an `if name == "eml"` branch.
- **The `InvokeSpecialist` port has two adapters:**
  - `invoke_agentcore_specialist.py`: boto3 `invoke_agent_runtime`, used when `runtime_arn` is set.
  - `invoke_specialist_in_process.py`: calls the specialist agent directly, used locally and in `DEMO=1`.

  This is what makes `just run langchain` and `just demo` work without AWS.
- **Parallel:** independent `ask_*` calls in one model turn run concurrently (the default tool node). Each call has a deadline (`SPECIALIST_TIMEOUT_SECONDS`, default 120). A timeout returns `ToolFailure(EXTERNAL_SERVICE_UNAVAILABLE)` for that task only.
- **Approval flow:**
  1. The model calls `act_eml("stop_channel", "1234567", {})`.
  2. The middleware interrupts, and the coordinator streams `approval_requested` with a new `approval_id`. The run pauses.
  3. The caller re-invokes with the same session and a `decision`. The coordinator resumes the graph:
     - **Rejected:** the tool returns "rejected by operator", and the run continues read-only.
     - **Approved:** the coordinator builds and signs an `ApprovedAction` bound to exactly the proposed action, resource, parameters and actor, with a 10-minute expiry. It sends that action to the specialist.
  4. The specialist returns `ActionResult`. The coordinator streams `action_completed`, then `verification_completed`.
- **A decision is valid only for its `approval_id`, in the same session, from the same actor.** Anything else streams `error(ApprovalRequired)`.
- **`write_todos` is removed.** It recorded nothing durable.

## 5. Prompts

- Each prompt file is one module exporting one constant and a `PROMPT_VERSION`.
- Prompts describe behavior only: evidence first, impact first, and say when evidence is insufficient. They do not restate tool schemas.
- Safety lives in sections 3–4 above, never in prompt text alone.

## 6. Observability

- The containers keep `opentelemetry-instrument` (ADOT). The CDK sets the AgentCore observability environment variables.
- Every `StreamEvent` is also logged as structured JSON with these fields:
  - `session.id`
  - `actor.id`
  - `specialist.name`
  - `tool.name`
  - `approval.id`
  - `prompt.version`
- Raw prompts, tool output and logs are not recorded by default.

## 7. Required tests

| Test | Proves |
|---|---|
| `tests/contract/verify_specialist_contract.py` | Each specialist, with fixtures and a fake model, accepts `SpecialistRequest` and emits valid `StreamEvent`s. It refuses writes without a valid `ApprovedAction` |
| `tests/contract/verify_approval_contract.py` | Coordinator: no approval means no `act_*` execution. A decision for another `approval_id`, session or actor is rejected. An expired approval is rejected |
| `tests/scenarios/<incident>/` | Fixture replay end to end: expected specialists and tools, diagnosis keywords, zero unapproved writes |
| `tests/unit/...` | Pure decisions: specialist tool generation from settings, `require_action_approval`, event serialization |

These are deterministic and offline. A fake chat model scripts the tool calls for contract tests. `just eval` runs the scenarios with the real model when credentials exist, and with the fake model otherwise.
