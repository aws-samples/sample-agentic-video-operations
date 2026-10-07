# Agent Contract: agentic-iops-streaming

One Strands agent on one AgentCore runtime serves every media domain. Domains plug in as
in-process **domain packs**. The agentic-iops-streaming sample is the only AgentCore runtime for the MediaLive and
MediaConnect samples (`agentic-iops-streaming` with `MEDIA_DOMAINS=medialive` runs only the MediaLive pack).

Enforces guidelines §3–4 (layers), §7 (typed data), §9 (safety), §11 (prompts), §12 (observability), §13 (tests).

## 1. agentic-iops-streaming (sample key `agentic-iops-streaming`, folder `samples/agentic-iops-streaming/`, distribution `agentic-iops-streaming`, package `agentic_iops_streaming`)

- **One `strands.Agent`, built per request.** The tools come from the selected packs, the prompt comes from skill metadata, and the hooks come from §4. There is no hardcoded tool list.
  - Only the Bedrock model client is cached across requests. A long-lived agent accumulates stale tool results.
  - `AGENTIC_IOPS_TOOL_BUDGET` (default 12) caps tool calls per request. Going over it ends the turn with `error(InvalidRequest)` and a next action.
- **Interrupt state survives between requests** through a Strands session manager keyed by `session_id`: `AgentCoreMemorySessionManager` when `MEMORY_ID` is set, `FileSessionManager` otherwise (local and `DEMO=1`).
- **One signing key per deployment.** AgentCore pins a session to one microVM only while it lives: after an idle timeout or a restart, the same session resumes in a new container. An approval paused in one container must therefore verify in another, so with `MEMORY_ID` set the runtime refuses to start unless `APPROVAL_SIGNING_KEY` is set (the agentic-iops-streaming CDK injects it from Secrets Manager). Locally, the coordinator and packs share one process, so the per-process key of `resolve_approval_signing_key` is enough.
- **Entrypoint:** `entrypoints/handle_agentcore_invocation.py` (`BedrockAgentCoreApp`, port 8080). It parses the request, builds the agent and streams events. Nothing else.
  - **Streaming:** the agent runs on a worker thread, and each `StreamEvent` is yielded as its hook records it, so `task_started` and `tool_called` reach the caller while tools and the model are still running.
  - **Caller identity fails closed:** a request without an actor (the header, or with JWT auth a valid bearer token) or a session id gets `error(InvalidRequest)` and runs nothing. Only `AGENTIC_IOPS_LOCAL_MODE=true`, which `just run agentic-iops-streaming` sets and the deployed runtime never does, substitutes one local operator and session.
  - **Trust boundary, IAM auth (the default):** the actor header is supplied by the caller and not verified. Any principal allowed to invoke the runtime can claim any actor id, so actor isolation (one operator's pending approvals hidden from another) holds only among principals trusted to invoke. The stack outputs `InvokePolicyArn` (invoke this runtime, nothing else); `AGENTIC_IOPS_INVOKER_ROLE_NAME` attaches it to one role at deploy.
  - **Trust boundary, JWT auth** (`AGENTIC_IOPS_JWT_DISCOVERY_URL` and `AGENTIC_IOPS_JWT_CLIENT_IDS` at deploy): the runtime accepts only bearer tokens. AgentCore verifies their signature, issuer, expiry and `client_id`, and forwards only the `Authorization` header. The actor is the token's `sub` (`domain/read_token_actor.py`), and an actor header is ignored. The runtime re-checks issuer, client, expiry and subject against `AGENTIC_IOPS_JWT_ISSUER` and `AGENTIC_IOPS_JWT_ALLOWED_CLIENTS`, which only the CDK sets, but doesn't re-verify the signature. It therefore refuses to start with `AGENTIC_IOPS_JWT_ISSUER` in local mode, where no authorizer is in front.
- **Commands:**
  - `just run agentic-iops-streaming` runs it locally.
  - `just demo` runs one investigation through the real agent and packs on `fixtures/input_loss`, with a scripted model instead of Bedrock. It creates no AWS client.
  - `just deploy agentic-iops-streaming` and `just destroy agentic-iops-streaming` (`scripts/manage_agentic_iops_streaming_stack.py`) deploy and remove it. `scripts/invoke_agentic_iops_streaming.py --actor <id>` sends a prompt or decision with the actor header; on a JWT-authorized runtime (stack output `InboundAuth=jwt`) it sends `AGENTIC_IOPS_BEARER_TOKEN` over HTTPS instead.
- **Deploy:** the agentic-iops-streaming CDK lives at `samples/agentic-iops-streaming/cdk/` and deploys the Strands agent on AgentCore.
  - `MEDIA_DOMAINS` (default `medialive,mediaconnect`) is passed as `-c mediaDomains=...` and becomes a runtime environment variable. Two packs offering the same tool name stop startup.
  - **Signing key:** one generated Secrets Manager secret. The runtime gets only `APPROVAL_SIGNING_KEY_SECRET_ARN` (environment variables are visible in the control plane); at startup the runtime reads the secret once and exports `APPROVAL_SIGNING_KEY`, so the coordinator and every pack in every container share it. A CDK test pins this.
  - **Never set by the CDK:** `AGENTIC_IOPS_LOCAL_MODE`, `DEMO`, or a plaintext `APPROVAL_SIGNING_KEY`. The runtime allowlists exactly one header (`requestHeaderAllowlist`): the actor header with IAM auth, `Authorization` with JWT auth. CDK tests pin both.
  - **IAM is declared by each pack, not by the coordinator.** Every pack's sample folder holds `samples/<key>/iam_permissions.json`, in this shape:

    ```json
    {"read":  [{"actions": ["medialive:DescribeChannel"], "resources": ["arn:aws:medialive:{region}:{account}:channel:*"]}],
     "write": [{"actions": ["medialive:StopChannel"],     "resources": ["arn:aws:medialive:{region}:{account}:channel:*"]}]}
    ```

    The agentic-iops-streaming CDK reads the file of each pack in `MEDIA_DOMAINS` (pack name = sample key = folder), fills in `{region}` and `{account}`, and grants every `read` statement. It grants `write` statements only with `-c allowWrites=true`. Those resources cover every selected-pack channel and flow in the deployed account and region by default. Optional `AGENTIC_IOPS_WRITE_TAG=Key=Value` is passed as `-c writeTag=Key=Value` and adds `aws:ResourceTag/Key = Value` to every pack write statement. The condition limits the resource; the HMAC-approved action still limits each call to the exact action, resource and parameters. `BatchUpdateSchedule` can use any schedule action supported by the adapter on a matching tagged channel, but only the approved parameters are signed and executed.

    A pack that calls Bedrock (the thumbnail check) writes the resource as `"{vision_model}"`, never a model ARN or `*`. The stack replaces it with the two ARNs of the configured vision model (`THUMBNAIL_MODEL_ID`): its inference profile in this account and region, and the foundation model behind it in any region, which cross-Region inference routes to. A pack therefore can't invoke any other model.
  - Adding a pack therefore needs no agentic-iops-streaming CDK edit.
  - A unit test checks that the file covers every AWS operation the pack's adapters call.
- **Foreign-auth services** (for example Hydrolix) are outside this sample.

**Request:**

```python
class AgenticIopsRequest(BaseModel):
    prompt: str | None = None                 # a new question
    decision: ApprovalDecision | None = None  # resumes a paused run
    # session_id comes from context.session_id (AgentCore requires at least 33 characters)
    # actor_id comes from the caller header in IAM mode, or the verified token sub in JWT mode

class ApprovalDecision(BaseModel):
    approval_id: str   # the interrupt id streamed in approval_requested
    approve: bool
    reason: str | None = None
```

**Response:** `StreamEvent` from `media_ops_contracts.stream_event`, one JSON object per event, encoded once. The entrypoint yields validated dicts and `BedrockAgentCoreApp` writes each as one SSE `data:` line.
- `task_started`: one per pack whose tool runs first in a turn.
- `tool_called`: name and read/write only, never raw output.
- `approval_requested`
- `action_completed`
- `verification_completed`
- `final_answer`: impact first, then evidence, then the next action.
- `usage_reported`: one per model-backed turn, immediately before the terminal
  `final_answer`, `approval_requested`, or `error`. It reports exact input,
  output, cache-read, cache-write, and total token counts. `estimated_usd` is
  the label **estimated list price, in-region on-demand, excludes caching and
  cross-region differences**, using the dated table in
  `media_ops_contracts/estimate_model_cost.py`. The table links to
  <https://aws.amazon.com/bedrock/pricing/>, was checked on 2026-10-06, and
  its $3/$15 and $1/$5 rates could not be confirmed through the AWS Price List
  API or public pricing page. Unknown exact model IDs return `null` cost.
- `error`

Exactly one terminal event ends a model-backed turn. Progress events come
first, then `usage_reported`, then that terminal event.

## 2. Domain packs (`packages/media_ops_contracts/src/media_ops_contracts/domain_pack.py`, framework-free)

```python
class WriteTool(BaseModel, frozen=True):
    function: Callable[..., ActionResult]   # typed; takes approved_action: ApprovedAction
    resource_parameter: str                 # e.g. "channel_id": the input that names the resource

class DomainPack(Protocol):
    name: str                               # "medialive"
    skill_paths: Sequence[Path]             # SKILL.md files shipped inside the package
    fixture_scenarios: Sequence[str]        # scenarios under fixtures/ this pack can replay
    def read_tools(self) -> Sequence[Callable[..., BaseModel | list[BaseModel]]]: ...
    def write_tools(self) -> Sequence[WriteTool]: ...
```

- **Registration:** each sample package exports `create_domain_pack() -> DomainPack` under the entry-point group `media_ops.domain_packs`:

  ```toml
  [project.entry-points."media_ops.domain_packs"]
  medialive = "medialive_mcp.domain_pack:create_domain_pack"
  ```
- **Which packs ship:** medialive, mediaconnect and hls (read-only HLS stream diagnostics from samples/hls-doctor). CMCD remains a standalone MCP sample.
- **Selection:** `MEDIA_DOMAINS=medialive,mediaconnect` chooses the packs. An unknown name fails at startup and lists the installed packs.
- **What a pack wraps:** plain typed functions over **the same adapters the sample's MCP server registers**. The pack builds its own clients and settings, including `DEMO` replay. The coordinator wraps the functions with `strands.tool`. A pack never imports Strands, the coordinator or another pack.
- **Cross-domain reasoning** (signal path from source to flow to channel) lives in coordinator skills, not in a pack.

## 3. Skills

- **Format:** one `SKILL.md` per skill, with YAML front-matter:

  ```markdown
  ---
  name: diagnose-input-loss          # unique across all loaded packs
  description: When a channel shows input loss or slate, find whether the fault is upstream.
  domain: medialive                  # or "coordinator" for cross-domain skills
  ---
  Steps, evidence to collect, tools to call, what to conclude, when evidence is insufficient.
  ```
- **Location:** `src/<pkg>/skills/<name>/SKILL.md`, shipped in the wheel. Coordinator skills live in `agentic_iops_streaming/skills/`.
- **Naming:** the front-matter `name` must equal the directory name. The coordinator refuses to start if any listed skill fails to parse or load by its name.
- **Prompt and loading:** the system prompt lists only each skill's `name` and `description`. The `load_skill(name)` tool returns the body, and an unknown name returns the list of names.
- **No S3 and no skill publishing** in this sample.
- **Safety stays in code:** skills describe behavior and evidence, never permission. Each skill file is one purpose (guidelines §11).

## 4. Writes: typed tools, approval through a Strands interrupt

**Write tools are registered only when `ALLOW_WRITES=true`.** Otherwise the model never sees them.

**The flow,** using Strands' human-in-the-loop API in strands-agents 1.x (checked against the installed 1.58.0 source):
1. **Interrupt.** A `BeforeToolCallEvent` hook runs for every write tool.
   - It builds an `ActionProposal`: action = the tool name, `resource_id` = the input named by `resource_parameter`, and parameters = the other inputs.
   - It sets `expires_at = now + 10 minutes`.
   - It then calls `event.interrupt("approve-write", reason={"proposal": proposal, "expires_at": expires_at})`. The reason is stored with the interrupt in the session, and the hook also keeps the pending approval (`approval_id` = the interrupt id, proposal, `expires_at`) in `agent.state` under `pending_approvals`, so the deadline survives between requests and the coordinator can refuse an unknown id, session or actor before resuming.
2. **Ask.** The run stops with `result.stop_reason == "interrupt"`. The coordinator streams `approval_requested` with `approval_id = interrupt.id`, the proposal, `risk` and `expires_at`.
3. **Resume.** The caller sends `AgenticIopsRequest(decision=...)` in the same session. Before resuming the agent, the coordinator refuses an unknown approval or one owned by another actor or session. A valid decision resumes with `agent([{"interruptResponse": {"interruptId": approval_id, "response": decision}}])`.
4. **On resume,** `event.interrupt(...)` returns the decision.
   - **Rejected:** the hook sets `event.cancel_tool = "rejected by operator"`.
   - **Approved:** before signing, the hook checks three things against the stored reason:
     - `now < expires_at`;
     - the pending tool call still names the same action and resource;
     - its parameters equal the proposal's.

     If any check fails, the hook sets `event.cancel_tool` and the coordinator streams `error(ApprovalExpired)` or `error(ApprovalRequired)`. Nothing is signed.
   - **Signing:** if every check passes, the hook signs an `ApprovedAction` for exactly that proposal, with the **same** `expires_at`, never a fresh one. It writes it into `event.tool_use["input"]["approved_action"]`, replacing any value the model supplied.
5. **Execute and verify.** The write adapter runs `require_action_approval`, acts once, verifies, and returns `ActionResult`. The coordinator streams `action_completed`, then `verification_completed`.

**Approval rules:**
- A decision for an unknown `approval_id`, another session or another actor streams `error(ApprovalRequired)`. The pending tool call is not run.
- The adapter still checks expiry and the signature (write_safe_tools.md §3) as a second line. The hook's checks don't replace them.

## 5. Observability and evals

- **Logging:** every `StreamEvent` is also logged as structured JSON with:
  - `session.id`
  - `actor.id`
  - `pack.name`
  - `tool.name`
  - `skill.name`
  - `approval.id`
  - `prompt.version`

  Raw tool output and prompts are not logged.
- **`just eval`** replays each scenario under `samples/agentic-iops-streaming/tests/scenarios/<name>/scenario.yaml`:
  - **Inputs:** the prompt, `MEDIA_DOMAINS`, the fixture scenario, and any decision.
  - **Expected:** tools, skills, diagnosis keywords, forbidden tools, and a maximum number of tool calls.
  - Write scenarios also name the expected action, before state, after state, and
    verification result.
- **Each scenario records:**
  - input and output tokens (`result.metrics.accumulated_usage`);
  - tool calls;
  - skills loaded;
  - wall-clock latency;
  - writes attempted.
  - verified action transitions.
- **Output:** the results print as a table, and `.cache/eval-results.json` is written for comparison across runs. This is the efficiency evidence.
- **Models:** the fake model is the default. The real model runs with `EVAL_MODEL=bedrock`.

## 6. Required tests

| Test | Proves |
|---|---|
| `packages/media_ops_contracts/tests/unit/test_domain_pack.py` | Entry-point discovery, selection by `MEDIA_DOMAINS`, and that an unknown pack fails with the list of installed packs |
| `samples/<key>/tests/pack/test_<key>_domain_pack.py` (each pack) | Its tools are the MCP server's adapters. Write tools need `ApprovedAction`. Its skills parse. `iam_permissions.json` covers every AWS operation its adapters call |
| `samples/agentic-iops-streaming/tests/contract/test_agentic_iops_approval_flow.py`, `test_agentic_iops_approval_checks.py` | With a scripted fake model: no write runs without approval; a rejection cancels; a decision for another approval, session or actor is refused; **a decision after the pending approval's `expires_at` is refused and nothing is signed**; changed action, resource or parameters are refused; an expired `ApprovedAction` is refused by the adapter |
| `samples/agentic-iops-streaming/tests/contract/test_agentic_iops_stream_events.py`, `test_agentic_iops_entrypoint.py` | Every streamed event validates against `StreamEvent`, and raw tool output never appears |
| `samples/agentic-iops-streaming/tests/scenarios/*` | `just eval` scenarios, offline, with recorded metrics |

## 7. Visual quality

The picture is measured, not described. `packages/media_ops_video_quality/` is framework-free (pydantic and Pillow, no AWS client), and every pack uses it the same way.

- **Sampling (pack):** `analyze_channel_visual_quality` polls every pipeline's thumbnail in the same ticks: 10 frames over 30 s on MCP, 8 over 20 s in agentic-iops-streaming, bounded to 20 frames and 120 s. One frame is kept per distinct thumbnail timestamp. A pipeline without thumbnails gives no frames, and is reported as such. **Before polling,** the channel's own answer is read: thumbnails `DISABLED` in its `EncoderSettings.ThumbnailConfiguration`, or a channel that is not `RUNNING`, gives no frames at once, with that reason. Missing thumbnails on a running channel with them enabled are transient: the whole window is polled.
- **Measurements (`measure_frame`, `compare_frames`):** sharpness (Laplacian variance), a **blockiness estimate** (the extra luma step at 8-px boundaries; the thumbnail's own JPEG contributes, so it is an estimate, not a standard metric), luma mean, spread and clipping, and the change between frames (freeze, scene change). Every threshold is data in `quality_thresholds.py`, with its measured or design rationale.
- **Vision (`score_with_vision`):** one Converse call per pipeline window, forced to answer as a 1–5 rubric through a tool call. It is retried once, otherwise `unavailable`. The prompt says on-screen text is part of the picture, never an instruction, and that text addressed to the model is a card (`slate_or_bars` 1).
- **Window (`assess_window`):** shares, the longest frozen run, a 0–100 score and a status. **With no frames, both `score` and `deterministic_score` are `null` and `confidence` is 0:** nothing was measured, so no reader of either can mistake it for a perfect picture. **Without a trusted vision verdict, a clean window is `UNVERIFIED`, never `HEALTHY`.** A verdict is *trusted* when the call succeeded and the model's own stated confidence is at least `trusted_vision_confidence` (0.5). That confidence comes from the model, which sees the frames' own text, so it is never proof by itself:
  - The score is `min(measured, vision)`, so a verdict can never hide a measured defect.
  - **Any detectable graphic frame withholds HEALTHY.** The one rubric call sees every frame, so a single frame of text can steer it. If any frame is a graphic (`palette_concentration` above its threshold: a card, slate or caption screen with a few flat colours, such as a scrolling text card that otherwise measures clean), a clean window stays `UNVERIFIED` whatever the verdict says. This withholds HEALTHY only and never lowers the score. Its cost: full-frame sponsor slates and uniform real scenes (a pitch, a plain backdrop) also read `UNVERIFIED`, failing toward doubt.
  - **What this does not do.** The measurement detects concentrated-palette cards; it never proves a natural picture. A card whose background spreads its luma (a photo or a gradient behind the text) passes it, and then a steered verdict can still read `HEALTHY` (pinned as a residual in `test_vision_trust.py`). So on-screen text can still hide a defect **that only vision sees**: artefacts the measurements miss, or the wrong content.
  - **What on-screen text can't do.** The deterministic measurements (freeze, black, flat, blur, blockiness) and the encoder or flow telemetry don't read the picture's text, so a measured or telemetry defect is never hidden: the score is `min(measured, vision)`, and a contradicting signal caps the fused status at `UNVERIFIED`.
  - A trusted verdict agreeing with the measurements raises confidence; disagreeing lowers it; an untrusted one can only lower it.
- **Fusion (`fuse_with_telemetry`):** each pipeline's finding is checked against the encoder's own signals over the last 15 minutes: MqcsFreezeFrameDetected, MqcsBlackFrameDetected, FillMsec, InputLossSeconds, and the active input. An agreeing signal raises confidence; a contradicting one lowers it, stops any other signal from raising it, and caps the fused `status` at `UNVERIFIED` (the window's own verdict stays in `picture_status`), so a picture never reads HEALTHY while the encoder reports a freeze or black. A signal that was not emitted is unknown; healthy-looking signals on an `UNVERIFIED` picture are `informational`, never agreement. Unreadable metrics are unknown too, with a note. Input health has three states: fill frames or input loss observed in the window point upstream (said as "observed within the last 15 minutes", not as current), both emitted and zero mean the input kept arriving, and neither emitted means unknown, so no root cause is claimed. A window judged degraded without one dominant defect (the vision rubric, or several measurements together) is `picture_problem`, with the model's evidence. The channel `status` is the worst fused pipeline status, over every pipeline.
- **Skill:** `assess-picture-quality` (medialive) tells the agent how to report findings, including that UNVERIFIED and unknown are not healthy.
- **Tests and fixtures:** synthetic, generated sequences (`scripts/generate_quality_fixtures.py`) calibrate every threshold with margins. `fixtures/frozen_output` (pipeline 0 frozen and confirmed by MQCS freeze, pipeline 1 moving) backs the tool tests and the agentic-iops-streaming `frozen_output` eval scenario.
- **MediaConnect (`analyze_flow_visual_quality`):** the same package, sampler bounds (`sampling_limits.py`) and rules over `DescribeFlowSourceThumbnail`, which returns one thumbnail per flow: of its source as it arrives, so a bad picture with a connected source points upstream of MediaConnect.
  - **Before polling,** the flow's `SourceMonitoringConfig` is read. Thumbnails disabled, or a flow that is not ACTIVE, gives no frames and `UNVERIFIED` with that reason; a thumbnail the service can't produce gives its own `ThumbnailMessages` as the reason. No protocol list is hard-coded: the service's answer decides. A refusal of the thumbnail call (BadRequest, NotFound) ends the window after that read; a busy or unavailable service is retried through it. **A window that ends without a thumbnail is capped at `UNVERIFIED` with that reason**, even if earlier frames measured clean: the picture's current state is unknown. With no frames and `SourceConnected` at 0 in the telemetry window, the next action names the disconnected sender first, since enabling thumbnails wouldn't produce a picture.
  - **Fusion** maps the flow's metrics to the same neutral `EncoderSignals`: freeze = `FrozenFramesBreaching`, black = `BlackFramesBreaching` (both only with content quality analysis on, otherwise unknown), input interrupted = `SourceDisconnections`, `SourceConnected` at 0, or `VideoStreamMissing`, over the last 60 minutes (`read_flow_metrics`' smallest window). `SourcePacketLossPercent` is evidence only. The P3 rules apply unchanged: a contradiction caps the fused status at `UNVERIFIED`, and healthy-looking signals on an `UNVERIFIED` picture are `informational`.
  - **Fixture and eval:** `fixtures/transport_freeze` (generated): the SRT source stays connected while its picture is frozen and content quality analysis reports frozen frames. The agentic-iops-streaming `transport_freeze` eval scenario expects `analyze_flow_visual_quality`, the keywords "frozen" and "upstream", and no writes.


## 8. Workflow discovery (contract for F3)

This section is the contract the workflow tools, fixtures, eval scenarios and skills are built against. Where code and this section differ, the code is wrong. A **workflow** is a live signal chain, such as EMX → EML → EMP → CloudFront, stored so that monitoring and diagnosis can walk the known path instead of guessing it.

**Owner:** the coordinator (this sample), not a domain pack. The tools, their IAM and their table live in the agentic-iops-streaming package and its CDK stack; the packs stay single-service. One setting, ALLOW_WORKFLOW_DISCOVERY (default true), registers all four tools. It is separate from `ALLOW_WRITES`, because none of them changes a media resource.

### 8.1 Tools

| Tool | Approval | Reads or writes |
|---|---|---|
| `discover_workflow(entry_point_arn: str, name: str)` | none | creates and deletes one transient signal map; reads the resources it maps |
| `save_workflow(workflow_id: str, version: str, entry_point_arn: str, name: str, content_sha256: str, approved_action: ApprovedAction)` | the §4 interrupt and `ApprovedAction` path, with `resource_parameter = "workflow_id"` | writes one new version to the workflow store; returns an `ActionResult` |
| `list_workflows(contains_arn: str \| None = None)` | none | the workflow store only |
| `get_workflow(workflow_id: str, version: int \| None = None)` | none | the workflow store only; `None` is the latest version |

- **discover_workflow** proposes; it never stores. It returns a `WorkflowProposal` and keeps it in the session's agent state under `workflow_proposals[workflow_id]`, replacing any earlier proposal for that id. When a stored workflow already contains the entry point, the proposal reuses that workflow's id, its `version` is the latest stored version + 1, and it carries a `WorkflowDiff` against that latest version. There is no separate rediscover tool.
- **discover_workflow needs no approval** because it leaves nothing behind. It MUST delete the signal map in a `finally`, on success, failure, timeout or cancellation (§8.3 gives the outcome rules).
- **save_workflow** is the only write, and its inputs are exactly what the §4 hook signs. Every input other than `workflow_id` and `approved_action` is a string, so the hook's `ActionProposal` is `action = "save_workflow"`, `resource_id = workflow_id` and `parameters = {version, entry_point_arn, name, content_sha256}`, all copied from the proposal the operator was shown. The model never passes a graph. The adapter then, in order:
  1. runs `require_action_approval` (action, resource, expiry, signature);
  2. loads `workflow_proposals[workflow_id]` from the session, and refuses with `RESOURCE_NOT_FOUND` if there is none;
  3. recomputes the proposal's `content_sha256` and refuses with `INVALID_REQUEST` unless it, `version`, `entry_point_arn` and `name` equal the signed parameters. So what is stored is exactly what was approved;
  4. writes the item with `attribute_not_exists(#v)`. If another save took that version first, it refuses with `INVALID_REQUEST` ("the workflow changed since it was shown; discover it again");
  5. reads the version back, then returns an `ActionResult`, the §4 write result the completion and verification events come from:
     - `resource_id` = `workflow_id`;
     - `before_state` = `"absent"`, or `"v<N> <sha256[:12]>"` for the latest stored version;
     - `after_state` = `"v<N+1> <sha256[:12]>"`, using the hash **observed in the read-back item**, never the signed one, so a mismatch is visible in the result;
     - `verified` is true only when the read-back item's `version` and `content_sha256` equal the signed values. When the hash differs, `verified` is false and `after_state` shows the stored hash.

     The agent shows the stored workflow by calling `get_workflow` afterwards.
- **Reads come from our store, never AWS.** `list_workflows(contains_arn=...)` is how a single channel or flow finds its workflow. Drift is a fresh `discover_workflow` compared with the stored version.

### 8.2 Records

All records are pydantic models, framework-free.

| Record | Fields |
|---|---|
| `WorkflowNode` | `arn: str`; `service: str`; `resource_type: str` (both read from the ARN by the table below); `name: str`; `sources: list[str]` and `destinations: list[str]` (ARNs, sorted) |
| `WorkflowEdge` | `source: str`, `destination: str` (ARNs); `inferred: bool = False` (true only for an edge added from MediaConnect outputs when the map lacks it) |
| `WorkflowProposal` | `workflow_id: str`; `version: int` (the version a save would write); `name: str`; `entry_point_arn: str`; `discovered_at: datetime` (UTC); `nodes: list[WorkflowNode]`; `failed_nodes: list[WorkflowNode]` (from `FailedMediaResourceMap`); `edges: list[WorkflowEdge]`; `content_sha256: str`; `diff: WorkflowDiff \| None` |
| `Workflow` | the proposal's fields without `diff`, plus `confirmed_by: str` (the verified actor of the approval) and `confirmed_at: datetime` (UTC) |
| `WorkflowSummary` | `workflow_id`, `name`, `entry_point_arn`, `latest_version: int`, `node_count: int`, `confirmed_at` |
| `WorkflowDiff` | `against_version: int`; `added_nodes`, `removed_nodes: list[str]` (ARNs, sorted); `added_edges`, `removed_edges: list[WorkflowEdge]` (sorted as below) |

- **Order:** nodes and failed nodes are sorted by `arn`. Edges are sorted by `(source, destination, inferred)`, each pair at most once. Every list in a record is in that order, so the same map always gives byte-identical records.
- **`content_sha256`** is the SHA-256 hex digest of `json.dumps({"entry_point_arn": ..., "nodes": [...], "failed_nodes": [...], "edges": [...]}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`, built from the sorted records with `model_dump(mode="json")`. It excludes `discovered_at`, `name`, `version` and `diff`, so rediscovering an unchanged chain gives the same hash.
- **`workflow_id`** is a lowercase slug of the name plus a short random suffix, at most 64 characters, and never an ARN or resource id.
- **`service` and `resource_type`** come from the ARN `arn:<partition>:<service>:<region>:<account>:<resource>`:

  | `service` | `resource` | `resource_type` |
  |---|---|---|
  | `mediaconnect` | `flow:<id>:<name>` | `flow` (the text before the first `:`) |
  | `medialive` | `channel:<id>`, `input:<id>` | `channel`, `input` |
  | `mediapackage` | `channels/<id>`, `origin_endpoints/<id>` | `channels`, `origin_endpoints` (the text before the first `/`) |
  | `mediapackagev2` | `channelGroup/<g>/channel/<c>[/originEndpoint/<e>]` | the last type in the path: `channel` or `originEndpoint` |
  | `mediatailor` | `playbackConfiguration/<name>` | `playbackConfiguration` |
  | `cloudfront` | `distribution/<id>` | `distribution` |
  | `s3` | `<bucket>` or `<bucket>/<key>` | `bucket`, or `object` when the resource has a `/` |
  | any other | any | the text before the first `/` or `:` |

  An ARN that doesn't have six `:`-separated fields is kept with `service = "unknown"` and `resource_type = "unknown"`, never dropped.
- **Failures** are `ToolFailure` with the `FailureKind` members in `media_ops_contracts.tool_failure`:
  - an unknown workflow or version is `RESOURCE_NOT_FOUND`;
  - a discovery timeout, or a `CREATE_FAILED` map, is `EXTERNAL_SERVICE_UNAVAILABLE` with the map's `ErrorMessage`;
  - an AWS error is classified by `classify_aws_error`;
  - the save refusals are listed in §8.1.

### 8.3 Discovery against the MediaLive signal-map API

Signal maps are a MediaLive API (botocore's `medialive` model, checked against the installed botocore on 2026-10-06). Creating and reading them costs nothing; only monitor deployment costs money, and no tool deploys monitors.

1. **Create:** `CreateSignalMap` with `DiscoveryEntryPointArn` = the entry point, `Name` = `agentic-iops-<workflow_id>` (1–255 characters), `Tags` = `{"managed-by": "agentic-iops-streaming"}`, and `RequestId` = a fresh UUID (the API's idempotency token). The response's `Id` identifies the map.
2. **Wait:** `GetSignalMap(Identifier=Id)` until `Status` leaves `CREATE_IN_PROGRESS`, using the bounded `wait_for_condition` (5 s interval, the same as botocore's `SignalMapCreated` waiter, and a 120 s deadline). `CREATE_COMPLETE` succeeds; `CREATE_FAILED` or the deadline fails. The status values are `CREATE_IN_PROGRESS`, `CREATE_COMPLETE`, `CREATE_FAILED`, `UPDATE_IN_PROGRESS`, `UPDATE_COMPLETE`, `UPDATE_REVERTED`, `UPDATE_FAILED`, `READY` and `NOT_READY`; only the first three occur for a new map.
3. **Read:** the fields mapped from the `GetSignalMap` response are `Id`, `Status`, `ErrorMessage`, `DiscoveryEntryPointArn`, `LastDiscoveredAt`, `MediaResourceMap` and `FailedMediaResourceMap`. Both maps are `{ARN: MediaResource}`, where `MediaResource` is `{"Name": str, "Sources": [{"Arn": str, "Name": str}], "Destinations": [{"Arn": str, "Name": str}]}`. Every key becomes a node; every source and destination pair becomes an edge.
4. **Delete:** `DeleteSignalMap(Identifier=Id)` in the `finally`, then one `GetSignalMap`, which must raise a `ClientError` that `classify_aws_error` classifies as `RESOURCE_NOT_FOUND` (`NotFoundException`). Any other answer is a cleanup failure, `AccessDeniedException` included. With a tag-conditioned grant, IAM may refuse the read of a deleted map before the service can say it's gone, and that refusal never counts as proof. The live probe (B3) records the real post-delete answer.

**Outcomes:** one rule covers every combination.

| Discovery (steps 1–3) | Cleanup (step 4) | Result |
|---|---|---|
| succeeded | verified | the proposal |
| succeeded | failed | a `ToolFailure` for the cleanup, and no proposal. Its kind is the delete's classified kind, or `UNEXPECTED_FAILURE` when the post-delete read isn't `RESOURCE_NOT_FOUND` |
| failed | verified | the primary `ToolFailure` |
| failed | failed | the primary `ToolFailure`, with the cleanup failure attached to it: its message ends with the cleanup sentence below |

- **The cleanup sentence** names the map: "Signal map `<Id>` was not deleted (`<kind>`)." Every cleanup failure is also logged at WARNING with the map id and the classified kind.
- **The cleanup's next action** is: "Delete it in the MediaLive console (Workflow monitor → Signal maps) or with `aws medialive delete-signal-map --identifier <Id>`." For a primary failure, it is appended to the primary failure's own next action.
- **No proposal reaches save_workflow** unless its map was verifiably deleted.
- **If the create call itself fails** with no `Id`, there is nothing to clean up, and the primary failure is the result.

**Fixtures** (replayed by `ReplayFixtureClient`, one scenario folder per chain under the repository's fixtures folder):
- **Recorded errors:** a response of the form `{"error": {"Code": "<AWS error code>", "Message": "..."}}`, either as the whole fixture or as one element of a `sequence`, raises the `botocore` `ClientError` AWS would have raised. Its operation name is the PascalCase operation, such as `GetSignalMap`, so adapters classify it as they classify the real one. An error entry without a `Code` is an invalid fixture (`INVALID_REQUEST`).
- **`medialive.create_signal_map.json`:** the create response (`Id`, `Arn`, `Name`, `Status` = `CREATE_IN_PROGRESS`, `Tags`).
- **`medialive.get_signal_map.json`:** a `sequence` of `CREATE_IN_PROGRESS`, then `CREATE_COMPLETE` with the full `MediaResourceMap`, then `{"error": {"Code": "NotFoundException", "Message": "Signal map not found"}}` for the post-delete check.
- **`medialive.delete_signal_map.json`:** `{}`.
- **The chains to record:** EMX flow → EML channel → EMP endpoint → CloudFront distribution (reusing the `srt_packet_loss` ids), and an EMX → EMX variant. Ids and ARNs are placeholders with account 111122223333.

### 8.4 The workflow store

- **Deployed:** one DynamoDB table in the coordinator's CDK stack, on-demand, with point-in-time recovery, encryption at rest and the stack's `RETAIN` policy. Its key is partition key `workflow_id` (S) and sort key `version` (N). Each item holds the `Workflow` record as attributes, plus `entry_point_arn` and `node_arns` (a string set, never empty: it always holds the entry point). An item over 350 KB is refused before writing, with an `INVALID_REQUEST` failure, staying under DynamoDB's 400 KB limit.
- **Attribute names:** `name` and `source` are DynamoDB reserved words, so every expression names attributes through `ExpressionAttributeNames` (`#n`, `#v`, …), never literally.
- **Local and demo:** JSON files at `.cache/workflows/<workflow_id>/v<version>.json`, one `Workflow` per file, under the ignored `.cache/`. A save creates the file exclusively, and fails if it exists (the local `attribute_not_exists`).
- **Versions are immutable.** A save writes `version` = latest + 1, conditioned on the item not existing (§8.1, step 4).
- **Workflows are account-wide,** shared by every operator of the deployment. Each version records who confirmed it and when; nothing is keyed by actor.
- **`get_workflow`** is one `Query` on `workflow_id`, latest first (`ScanIndexForward=False`, `Limit=1`), or one `GetItem` for a given version.
- **`list_workflows`** pages through one `Scan` to the end (following `LastEvaluatedKey`), with a projection of the summary fields and `node_arns`.
  - It collapses the versions to exactly one `WorkflowSummary` per `workflow_id`, taken from its highest version.
  - With `contains_arn`, it keeps the workflows whose **latest** version's `node_arns` contain that ARN.
  - It sorts the result by `name`, then `workflow_id`.
  - A sample's store holds tens of workflows, so a scan stays cheap, and a secondary index isn't needed.

### 8.5 IAM (runtime role)

| Actions | Resource | Condition |
|---|---|---|
| `medialive:CreateSignalMap`, `medialive:CreateTags` | `arn:aws:medialive:<region>:<account>:signal-map:*` | `aws:RequestTag/managed-by` = `agentic-iops-streaming` and `aws:TagKeys` = `["managed-by"]`. The Service Authorization Reference lists `CreateTags` as a dependent action of `CreateSignalMap` |
| `medialive:GetSignalMap`, `medialive:DeleteSignalMap` | `arn:aws:medialive:<region>:<account>:signal-map:*` | `aws:ResourceTag/managed-by` = `agentic-iops-streaming` |
| `dynamodb:PutItem`, `dynamodb:GetItem`, `dynamodb:Query`, `dynamodb:Scan` | the workflow table's ARN only | none |
| The discovery reads of the services a map can contain (MediaConnect, MediaLive, MediaPackage v1 and v2, MediaTailor, CloudFront, S3), read-only | as narrow as each API allows | none |

- **No other signal-map action is granted:** no `StartUpdateSignalMap`, no `ListSignalMaps` (the store is the list), and no monitor deployment.
- **The discovery reads are not final.** Whether discovery runs with the caller's credentials, and which reads it needs, is settled by the live probe (B3) on a sandbox account, and the list is trimmed to what the probe shows is used. Each `*` resource gets a reasoned entry in the IAM gate's allowlist, as today.
- **The tag conditions are the scope:** the runtime can create, read and delete only the maps it tagged, and never touches a map an operator made in the console.
- **A residual for B3:** with only `aws:RequestTag`, `CreateTags` would also let the role add our tag to an existing operator map. No adapter calls `CreateTags`, so the model can't reach it. If the probe shows create-time tagging works without `CreateTags`, it is removed; otherwise this residual stays recorded here.

### 8.6 Required tests

- **Discovery:**
  - against the fixture chains, it returns the expected nodes and edges, in the §8.2 order, with the same `content_sha256` on every run;
  - each row of the §8.3 outcome table, including a cleanup failure attached to a primary failure, and an `AccessDeniedException` post-delete read counted as a cleanup failure.
- **save_workflow:** writes nothing when:
  - there is no approval;
  - the approval is for another workflow;
  - the approval is expired, or its signature is bad;
  - the signed hash, version, entry point or name differs from the session's proposal;
  - there is no proposal in the session;
  - the version was taken first by another save.

  With a valid approval, it writes version N+1, reads it back, and returns an `ActionResult` with the `before_state`, `after_state` and `verified` of §8.1, step 5. A read-back whose version or hash differs gives `verified=false`, with `after_state` carrying the stored hash (`"v<N+1> <stored sha256[:12]>"`), not the signed one.
- **Rediscovery:** discovering a stored entry point carries a `WorkflowDiff` against the latest version, and an unchanged chain has the same hash.
- **list_workflows:**
  - it returns one summary per workflow, at its highest version, across several Scan pages;
  - `contains_arn` finds a workflow from any node of its latest version, and returns nothing for an unknown ARN.
- **ARN parsing:** every row of the §8.2 table, plus an unparseable ARN.
- **The setting:** with ALLOW_WORKFLOW_DISCOVERY off, none of the four tools is registered.
- **CDK:** the CDK tests pin the tag conditions, the table-only DynamoDB grant, and that no other signal-map action appears.
- **Replay:** the replay client's recorded-error entry has its own tests in `media_ops_contracts`.
