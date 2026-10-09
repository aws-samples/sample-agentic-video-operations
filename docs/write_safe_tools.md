# Tool Contract

How every tool is written. This covers MCP server tools (`cmcd`, `mediaconnect`, `medialive`, `hls-doctor`) and the domain packs that reuse them in `agentic-iops-streaming` (extend_agentic_iops_streaming.md §2).

Enforces guidelines §1 (names), §3 (adapters), §7 (typed data), §8 (decisions vs effects), §9 (safety in code), §10 (failures), §13 (tests).

## 1. One action per adapter

```
src/medialive_mcp/
  adapters/media_live/describe_channel.py   # read
  adapters/media_live/stop_channel.py       # write
  adapters/cloudwatch/read_channel_metrics.py
  tool_surface/create_read_tools.py         # shared read-tool surface
  tool_surface/create_write_tools.py        # shared coordinator write-tool surface
  entrypoints/serve_mcp.py                  # MCP transport and approval wiring
```

- Each adapter file exposes one public function, named `verb_object`: `describe_channel`, `stop_channel`, `read_channel_metrics`.
- Adapters receive their AWS client as an argument, created by `create_aws_client()`. They never build clients themselves at import time.
- Adapters translate. They do not decide policy, such as risk, approval or which channel to pick.
- **The sample's MCP entrypoint and its domain pack (extend_agentic_iops_streaming.md §2) expose the same plain, typed adapter functions.**
  - Only the coordinator wraps them with Strands. Adapters and packs never import an agent framework.
  - Read-tool factories are shared. MCP and coordinator write registration differ because their approval transports differ, but both call the same write adapters. Nothing is `COPY`ed.

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
- Map botocore error codes once, in `media_ops_contracts.classify_aws_error`.
- Every AWS client sets explicit timeouts and bounded retries (`connect_timeout=5`, `read_timeout=30`, `max_attempts=3`, standard retry mode).

## 3. Writes: approve, act, verify

**Read and write are separate.** Every MCP tool declares one annotation:

```python
@mcp.tool(annotations={"readOnlyHint": True})
def describe_channel(...): ...

@mcp.tool(annotations={"destructiveHint": True, "idempotentHint": True})
def stop_channel(...): ...
```

**Media-resource write tools are registered only when `ALLOW_WRITES=true`.** With the default `false`, those write tools do not exist, so a model cannot call them. The one exception is agentic-iops-streaming's `save_workflow`, an approved write to the sample's own workflow store, gated by `ALLOW_WORKFLOW_DISCOVERY` instead.

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
def stop_channel(approved_action, media_live, check, policy) -> ActionResult:
    require_action_approval(  # decision
        approved_action,
        action="stop_channel",
        signing_key=check.signing_key,
        now=check.now,
    )
    require_signed_parameters(approved_action, {})  # stop takes no inputs beyond the channel
    before = describe_channel(media_live, approved_action.resource_id).state
    media_live.stop_channel(ChannelId=approved_action.resource_id)               # effect
    after = wait_for_condition(
        lambda: describe_channel(media_live, approved_action.resource_id).state,
        lambda state: state is ChannelState.IDLE,
        policy,
    )
    return ActionResult(
        approval_id=approved_action.approval_id,
        action="stop_channel",
        resource_id=approved_action.resource_id,
        before_state=before,
        after_state=after,
        verified=after is ChannelState.IDLE,
    )
```

- `require_action_approval(approved_action, *, action, signing_key, now, resource_id=None)` rejects a missing approval, an action or resource that doesn't match, a bad signature (`ApprovalRequired`) or an expired approval (`ApprovalExpired`). It is a pure decision: time is passed in as `now`.
- **A write must check its signed parameters.** `require_action_approval` never reads `parameters`, because only the write knows its own inputs. A signature proves the operator approved *some* inputs, not the ones this call carries. So every write also calls `require_signed_parameters(approved_action, expected)` with exactly the inputs it will act on, and acts on those, not on loose arguments. A write that takes no inputs beyond its resource passes `{}`. Values compare as the approval hook records them: as `str`, with `None` left out. A difference names the inputs that differ, never their values, and is refused as `ApprovalRequired`.
- `verify_<resource>_state` polls with a bounded deadline (default 120 s) and returns the observed state. A write result without verification is a contract violation.
- start, stop and input switch are idempotent in MediaLive and MediaConnect. They need no idempotency key. Document this in the adapter docstring.
- start and stop read the state first: a channel or flow already in the target state is a verified no-op. MediaLive also waits without another write when the channel is already `STARTING` toward a start or `STOPPING` toward a stop. An input switch whose target is already active on every pipeline, or whose same named immediate action is pending for that target, is likewise a verified no-op. Tests pin that no write call is made.
- Raw write client calls (`client.stop_channel(...)`) appear **only** inside the write adapter.

**Who creates the `ApprovedAction`** depends on the entrypoint. The adapter rule does not change:

| Entrypoint | Who approves | How the `ApprovedAction` is created |
|---|---|---|
| MCP stdio (Claude Code, Kiro, Q) | The human at the MCP client. Before any change the server sends an MCP elicitation showing the action, resource and parameters, and the user must type the exact resource id (`confirm_with_operator.py`). The model's tool arguments can't answer it. A different id, a decline or a cancel changes nothing, and a client that doesn't support form elicitation, or fails to ask, can't write. **This assumes a trusted client that shows the question to a person:** the server sees only the answer, so a client that answers elicitations by itself defeats it. Keep `ALLOW_WRITES` off unless you trust the client. The client's own tool-permission prompt, if any, comes on top | The entrypoint signs it with the local key after the user's answer |
| Domain pack in the coordinator | The coordinator's Strands interrupt (extend_agentic_iops_streaming.md §4) | The coordinator's approval hook signs it. The adapter verifies |

**Untrusted input.** Treat everything a tool returns as data, never as instructions. Tool results are not passed back into system prompts. That includes:

- logs, resource names, tags and metric labels;
- **thumbnails and the text in them**: a picture can show text addressed to a model;
- **vision-model output**: a frame description or rubric verdict may repeat or obey that text, so it never proves a picture healthy by itself (extend_agentic_iops_streaming.md §7);
- **viewer telemetry**: CMCD session and content ids, user agents and URL paths are set by the public.

**Infrastructure policies.** `Principal: "*"` is allowed only in service
endpoint policies, and those policies must be narrower than the service
default. Statements for stack-owned resources must add an account or stronger
condition; service-signed callback paths may remain resource-scoped without a
principal-account condition.

## 4. Demo mode and fixtures

- `create_aws_client(service, settings)` returns a boto3 client. With `DEMO=1` it returns a `ReplayFixtureClient`.
- `ReplayFixtureClient` answers `client.<operation>(**kwargs)` and `get_paginator(op).paginate(**kwargs)` from `fixtures/<scenario>/<service>.<operation>.json`. A fixture is either one response, or `{"sequence": [r1, r2, …]}`, consumed in order with the last one repeating. This is how a describe call returns the before state, then the after state. A response `{"error": {"Code": "…", "Message": "…"}}`, as the whole fixture or as one sequence element, raises the `ClientError` AWS would have raised, so a recorded failure is classified like a real one. `DEMO_SCENARIO` selects the scenario.
- A missing fixture raises `ToolFailure(INVALID_REQUEST, "No fixture for medialive.describe_channel in scenario input_loss")`. It never silently returns empty data.
- Write operations in demo mode record the call and return the fixture's "after" state. They never touch AWS.
- AWS-backed samples record sanitized AWS responses, with every account id, ARN, IP and name replaced by placeholders (`111122223333`, `demo-channel`). A non-AWS source records its own sanitized format: HLS Doctor replays `http.exchanges.json`.

## 5. Shared code: `packages/media_ops_contracts/`

| Module | Exists to |
|---|---|
| `approved_action.py` | define `ApprovedAction` and `sign_approved_action()` |
| `require_action_approval.py` | reject actions that are unapproved, mismatched or expired |
| `require_signed_parameters.py` | reject a write whose inputs differ from the signed `parameters` |
| `tool_failure.py` | define `FailureKind` and `ToolFailure` |
| `classify_aws_error.py` | map botocore errors to `FailureKind` |
| `call_aws_operation.py` | call one AWS operation, or every page with `collect_pages`, and classify SDK errors (`BotoCoreError` and `ClientError`) |
| `stream_event.py` | define `StreamEvent` (extend_agentic_iops_streaming.md) |
| `create_aws_client.py` | build a regional boto3 client with timeouts, or the replay client |
| `replay_fixture_client.py` | answer AWS calls from fixtures |
| `load_fixture.py` | read one fixture file (also used for non-AWS sources such as InfluxDB) |

Keep each module focused on the action in this table. The package imports pydantic, boto3 and botocore only, with no MCP, Strands or AgentCore dependency.

## 6. Required tests per tool

- **Read adapter:** a fixture-backed unit test asserting the typed result.
- **Write adapter:** negative tests for:
  - no approval,
  - the wrong resource,
  - the wrong action,
  - an expired approval,
  - a bad signature,
  - inputs that differ from the signed parameters: one changed, one extra.

  `test_every_write_checks_its_signed_parameters.py` in agentic-iops-streaming runs the last case against every registered write: each pack's and the coordinator's `save_workflow`.

  Plus a positive test asserting before, after and `verified`.
- **Entrypoint:** with `ALLOW_WRITES=false`, the media-resource write tool is not registered.
- **Test names describe behavior:** `test_stop_channel_rejects_approval_for_another_channel`.
