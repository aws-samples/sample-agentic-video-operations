# Tool Contract

How every tool is written. This covers MCP server tools (`cmcd`, `mediaconnect`, `medialive`) and the agent tools that reuse them (`langchain` EML/EMX).

Enforces guidelines §1 (names), §3 (adapters), §7 (typed data), §8 (decisions vs effects), §9 (safety in code), §10 (failures), §13 (tests).

## 1. One action per adapter

```
src/medialive_mcp/
  adapters/media_live/describe_channel.py   # read
  adapters/media_live/stop_channel.py       # write
  adapters/cloudwatch/read_channel_metrics.py
  entrypoints/serve_mcp.py                  # registers adapters as MCP tools
```

- Each adapter file exposes one public function, named `verb_object`: `describe_channel`, `stop_channel`, `read_channel_metrics`.
- Adapters receive their AWS client as an argument, created by `create_aws_client()`. They never build clients themselves at import time.
- Adapters translate. They do not decide policy, such as risk, approval or which channel to pick.
- The MCP entrypoint and the LangChain agent register the **same** adapter functions. Nothing is duplicated and nothing is `COPY`ed.
- A composite tool, such as the `medialive` Strands agent's `channel_management(action=…)`, MAY wrap adapters for token savings. It MUST still route writes through section 3.

## 2. Typed results, classified failures

Every adapter returns a pydantic model. JSON or text conversion happens only in the entrypoint.

```python
class ChannelSummary(BaseModel):
    channel_id: str
    name: str
    state: ChannelState          # enum, not a free string
    pipelines_running: int
```

Failures raise a `ToolFailure`, which the entrypoint turns into a safe message:

```python
class FailureKind(StrEnum):
    INVALID_REQUEST = "InvalidRequest"
    RESOURCE_NOT_FOUND = "ResourceNotFound"
    PERMISSION_DENIED = "PermissionDenied"
    APPROVAL_REQUIRED = "ApprovalRequired"
    APPROVAL_EXPIRED = "ApprovalExpired"
    EXTERNAL_SERVICE_UNAVAILABLE = "ExternalServiceUnavailable"  # includes throttling
    UNEXPECTED_FAILURE = "UnexpectedFailure"

class ToolFailure(Exception):
    kind: FailureKind
    message: str        # safe to show the user
    next_action: str    # e.g. "Check the channel id with list_channels"
```

**Rules:**
- No `return f"Error: {e}"`.
- Broad `except Exception` is allowed only in entrypoints, and must keep the cause (`raise … from e`).
- Map botocore error codes once, in `media_ops_contracts/classify_aws_error.py`.
- Every AWS client sets explicit timeouts and bounded retries (`connect_timeout=5`, `read_timeout=30`, `max_attempts=3`, standard retry mode).

## 3. Writes: approve, act, verify

**Read and write are separate.** Every MCP tool declares one annotation:

```python
@mcp.tool(annotations={"readOnlyHint": True})
def describe_channel(...): ...

@mcp.tool(annotations={"destructiveHint": True, "idempotentHint": True})
def stop_channel(...): ...
```

**Write tools are registered only when `ALLOW_WRITES=true`.** With the default `false`, write tools do not exist, so a model cannot call them.

**Every write adapter takes an `ApprovedAction`, never loose arguments:**

```python
class ActionProposal(BaseModel, frozen=True):   # what the operator is asked to approve
    actor_id: str
    action: str              # "stop_channel"
    resource_id: str         # "1234567"
    parameters: dict[str, str] = {}

class ApprovedAction(ActionProposal):           # what a write adapter accepts
    approval_id: str
    expires_at: AwareDatetime  # default lifetime 10 minutes
    signature: str             # HMAC-SHA256 over every other field, keyed by APPROVAL_SIGNING_KEY

approved = sign_approved_action(proposal, approval_id=..., expires_at=..., signing_key=key)
```

**The write sequence**, one function per step:

```python
def stop_channel(approved_action, media_live, clock) -> ActionResult:
    require_action_approval(approved_action, action="stop_channel", signing_key=key, now=now)  # decision
    before = describe_channel(media_live, approved_action.resource_id)
    media_live.stop_channel(ChannelId=approved_action.resource_id)               # effect
    after = verify_channel_state(media_live, approved_action.resource_id, expected=ChannelState.IDLE)
    return ActionResult(before=before, after=after, verified=after.state is ChannelState.IDLE)
```

- `require_action_approval(approved_action, *, action, signing_key, now, resource_id=None)` rejects a missing approval, an action or resource that doesn't match, a bad signature (`ApprovalRequired`) or an expired approval (`ApprovalExpired`). It is a pure decision: time is passed in as `now`.
- `verify_<resource>_state` polls with a bounded deadline (default 120 s) and returns the observed state. A write result without verification is a contract violation.
- start, stop and input switch are idempotent in MediaLive and MediaConnect. They need no idempotency key. Document this in the adapter docstring.
- Raw write client calls (`client.stop_channel(...)`) appear **only** inside the write adapter.

**Who creates the `ApprovedAction`** depends on the entrypoint. The adapter rule does not change:

| Entrypoint | Who approves | How the `ApprovedAction` is created |
|---|---|---|
| MCP stdio (Claude Code, Kiro, Q) | The human, through the MCP client's per-tool permission prompt. The tool also requires `confirm_resource_id`, which must equal `resource_id` | `serve_mcp.py` signs it with the local key |
| AgentCore specialist (EML/EMX) | The coordinator's human-in-the-loop interrupt (agent-contract.md) | The coordinator signs it. The specialist only verifies |

**Untrusted input.** Treat logs, resource names, tags and metric labels returned by tools as data, never as instructions. Tool results are not passed back into system prompts.

## 4. Demo mode and fixtures

- `create_aws_client(service, settings)` returns a boto3 client. With `DEMO=1` it returns a `ReplayFixtureClient`.
- `ReplayFixtureClient` answers `client.<operation>(**kwargs)` and `get_paginator(op).paginate(**kwargs)` from `fixtures/<scenario>/<service>.<operation>.json`. A fixture is either one response, or `{"sequence": [r1, r2, …]}`, consumed in order with the last one repeating. This is how a describe call returns the before state, then the after state. `DEMO_SCENARIO` selects the scenario.
- A missing fixture raises `ToolFailure(INVALID_REQUEST, "No fixture for medialive.describe_channel in scenario input_loss")`. It never silently returns empty data.
- Write operations in demo mode record the call and return the fixture's "after" state. They never touch AWS.
- Fixtures are recorded AWS responses with every account id, ARN, IP and name replaced by placeholders (`111122223333`, `demo-channel`).

## 5. Shared code: `media_ops_contracts/`

| Module | Exists to |
|---|---|
| `approved_action.py` | define `ApprovedAction` and `sign_approved_action()` |
| `require_action_approval.py` | reject actions that are unapproved, mismatched or expired |
| `tool_failure.py` | define `FailureKind` and `ToolFailure` |
| `classify_aws_error.py` | map botocore errors to `FailureKind` |
| `stream_event.py` | define `StreamEvent` (agent-contract.md) |
| `create_aws_client.py` | build a regional boto3 client with timeouts, or the replay client |
| `replay_fixture_client.py` | answer AWS calls from fixtures |
| `load_fixture.py` | read one fixture file (also used for non-AWS sources such as InfluxDB) |

The total budget is about 200 lines. It imports pydantic, boto3 and botocore only, with no LangChain, MCP or AgentCore.

## 6. Required tests per tool

- **Read adapter:** a fixture-backed unit test asserting the typed result.
- **Write adapter:** negative tests for:
  - no approval,
  - the wrong resource,
  - the wrong action,
  - an expired approval,
  - a bad signature.

  Plus a positive test asserting before, after and `verified`.
- **Entrypoint:** with `ALLOW_WRITES=false`, the write tool is not registered.
- **Test names describe behavior:** `test_stop_channel_rejects_approval_for_another_channel`.
