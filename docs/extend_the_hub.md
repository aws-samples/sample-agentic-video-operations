# Agent Contract: the media ops hub

One Strands agent on one AgentCore runtime serves every media domain. Domains plug in as
in-process **domain packs**. The hub is the only AgentCore runtime for the MediaLive and
MediaConnect samples (`hub` with `MEDIA_DOMAINS=medialive` runs only the MediaLive pack).

Enforces guidelines §3–4 (layers), §7 (typed data), §9 (safety), §11 (prompts), §12 (observability), §13 (tests).

## 1. Hub (sample key `hub`, folder `samples/hub/`, distribution `media-ops-hub`, package `media_ops_hub`)

- **One `strands.Agent`, built per request.** The tools come from the selected packs, the prompt comes from skill metadata, and the hooks come from §4. There is no hardcoded tool list.
  - Only the Bedrock model client is cached across requests. A long-lived agent accumulates stale tool results.
  - `HUB_TOOL_BUDGET` (default 12) caps tool calls per request. Going over it ends the turn with `error(InvalidRequest)` and a next action.
- **Interrupt state survives between requests** through a Strands session manager keyed by `session_id`: `AgentCoreMemorySessionManager` when `MEMORY_ID` is set, `FileSessionManager` otherwise (local and `DEMO=1`).
- **One signing key per deployment.** AgentCore pins a session to one microVM only while it lives: after an idle timeout or a restart, the same session resumes in a new container. An approval paused in one container must therefore verify in another, so with `MEMORY_ID` set the hub refuses to start unless `APPROVAL_SIGNING_KEY` is set (the hub CDK injects it from Secrets Manager). Locally, hub and packs share one process, so the per-process key of `resolve_approval_signing_key` is enough.
- **Entrypoint:** `entrypoints/handle_agentcore_invocation.py` (`BedrockAgentCoreApp`, port 8080). It parses the request, builds the agent and streams events. Nothing else.
  - **Streaming:** the agent runs on a worker thread, and each `StreamEvent` is yielded as its hook records it, so `task_started` and `tool_called` reach the caller while tools and the model are still running.
  - **Caller identity fails closed:** a request without an actor (the header, or with JWT auth a valid bearer token) or a session id gets `error(InvalidRequest)` and runs nothing. Only `HUB_LOCAL_MODE=true`, which `just run hub` sets and the deployed runtime never does, substitutes one local operator and session.
  - **Trust boundary, IAM auth (the default):** the actor header is supplied by the caller and not verified. Any principal allowed to invoke the runtime can claim any actor id, so actor isolation (one operator's pending approvals hidden from another) holds only among principals trusted to invoke. The stack outputs `InvokePolicyArn` (invoke this runtime, nothing else); `HUB_INVOKER_ROLE_NAME` attaches it to one role at deploy.
  - **Trust boundary, JWT auth** (`HUB_JWT_DISCOVERY_URL` and `HUB_JWT_CLIENT_IDS` at deploy): the runtime accepts only bearer tokens. AgentCore verifies their signature, issuer, expiry and `client_id`, and forwards only the `Authorization` header. The actor is the token's `sub` (`domain/read_token_actor.py`), and an actor header is ignored. The hub re-checks issuer, client, expiry and subject against `HUB_JWT_ISSUER` and `HUB_JWT_ALLOWED_CLIENTS`, which only the CDK sets, but doesn't re-verify the signature. It therefore refuses to start with `HUB_JWT_ISSUER` in local mode, where no authorizer is in front.
- **Commands:**
  - `just run hub` runs it locally.
  - `just demo` runs one investigation through the real hub and packs on `fixtures/input_loss`, with a scripted model instead of Bedrock. It creates no AWS client.
  - `just deploy hub` and `just destroy hub` (`scripts/manage_hub_stack.py`) deploy and remove it. `scripts/invoke_hub.py --actor <id>` sends a prompt or decision with the actor header; on a JWT-authorized hub (stack output `InboundAuth=jwt`) it sends `HUB_BEARER_TOKEN` over HTTPS instead.
- **Deploy:** the hub CDK lives at `samples/hub/cdk/` and deploys the Strands agent on AgentCore.
  - `MEDIA_DOMAINS` (default `medialive,mediaconnect`) is passed as `-c mediaDomains=...` and becomes a runtime environment variable. Two packs offering the same tool name stop startup.
  - **Signing key:** one generated Secrets Manager secret. The runtime gets only `APPROVAL_SIGNING_KEY_SECRET_ARN` (environment variables are visible in the control plane); at startup the hub reads the secret once and exports `APPROVAL_SIGNING_KEY`, so the hub and every pack in every container share it. A CDK test pins this.
  - **Never set by the CDK:** `HUB_LOCAL_MODE`, `DEMO`, or a plaintext `APPROVAL_SIGNING_KEY`. The runtime allowlists exactly one header (`requestHeaderAllowlist`): the actor header with IAM auth, `Authorization` with JWT auth. CDK tests pin both.
  - **IAM is declared by each pack, not by the hub.** Every pack's sample folder holds `samples/<key>/iam_permissions.json`, in this shape:

    ```json
    {"read":  [{"actions": ["medialive:DescribeChannel"], "resources": ["arn:aws:medialive:{region}:{account}:channel:*"]}],
     "write": [{"actions": ["medialive:StopChannel"],     "resources": ["arn:aws:medialive:{region}:{account}:channel:*"]}]}
    ```

    The hub CDK reads the file of each pack in `MEDIA_DOMAINS` (pack name = sample key = folder), fills in `{region}` and `{account}`, and grants every `read` statement. It grants `write` statements only with `-c allowWrites=true`. Those resources cover every selected-pack channel and flow in the deployed account and region by default. Optional `HUB_WRITE_TAG=Key=Value` is passed as `-c writeTag=Key=Value` and adds `aws:ResourceTag/Key = Value` to every pack write statement. The condition limits the resource; the HMAC-approved action still limits each call to the exact action, resource and parameters. `BatchUpdateSchedule` can use any schedule action supported by the adapter on a matching tagged channel, but only the approved parameters are signed and executed.
  - Adding a pack therefore needs no hub CDK edit.
  - A unit test checks that the file covers every AWS operation the pack's adapters call.
- **Foreign-auth services** (for example Hydrolix) are outside this hub sample.

**Request:**

```python
class HubRequest(BaseModel):
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
- **Which packs ship:** medialive and mediaconnect. CMCD remains a standalone MCP sample.
- **Selection:** `MEDIA_DOMAINS=medialive,mediaconnect` chooses the packs. An unknown name fails at startup and lists the installed packs.
- **What a pack wraps:** plain typed functions over **the same adapters the sample's MCP server registers**. The pack builds its own clients and settings, including `DEMO` replay. The hub wraps the functions with `strands.tool`. A pack never imports Strands, the hub or another pack.
- **Cross-domain reasoning** (signal path from source to flow to channel) lives in hub skills, not in a pack.

## 3. Skills

- **Format:** one `SKILL.md` per skill, with YAML front-matter:

  ```markdown
  ---
  name: diagnose-input-loss          # unique across all loaded packs
  description: When a channel shows input loss or slate, find whether the fault is upstream.
  domain: medialive                  # or "hub" for cross-domain skills
  ---
  Steps, evidence to collect, tools to call, what to conclude, when evidence is insufficient.
  ```
- **Location:** `src/<pkg>/skills/<name>/SKILL.md`, shipped in the wheel. Hub-level skills live in `media_ops_hub/skills/`.
- **Naming:** the front-matter `name` must equal the directory name. The hub refuses to start if any listed skill fails to parse or load by its name.
- **Prompt and loading:** the system prompt lists only each skill's `name` and `description`. The `load_skill(name)` tool returns the body, and an unknown name returns the list of names.
- **No S3 and no skill publishing** in this sample.
- **Safety stays in code:** skills describe behavior and evidence, never permission. Each skill file is one purpose (guidelines §11).

## 4. Writes: typed tools, approval through a Strands interrupt

**Write tools are registered only when `ALLOW_WRITES=true`.** Otherwise the model never sees them.

**The flow,** using Strands' human-in-the-loop API in strands-agents 1.x (checked against the installed 1.58.0 source):
1. **Interrupt.** A `BeforeToolCallEvent` hook runs for every write tool.
   - It builds an `ActionProposal`: action = the tool name, `resource_id` = the input named by `resource_parameter`, and parameters = the other inputs.
   - It sets `expires_at = now + 10 minutes`.
   - It then calls `event.interrupt("approve-write", reason={"proposal": proposal, "expires_at": expires_at})`. The reason is stored with the interrupt in the session, and the hook also keeps the pending approval (`approval_id` = the interrupt id, proposal, `expires_at`) in `agent.state` under `pending_approvals`, so the deadline survives between requests and the hub can refuse an unknown id, session or actor before resuming.
2. **Ask.** The run stops with `result.stop_reason == "interrupt"`. The hub streams `approval_requested` with `approval_id = interrupt.id`, the proposal, `risk` and `expires_at`.
3. **Resume.** The caller sends `HubRequest(decision=...)` in the same session. Before resuming the agent, the hub refuses an unknown approval or one owned by another actor or session. A valid decision resumes with `agent([{"interruptResponse": {"interruptId": approval_id, "response": decision}}])`.
4. **On resume,** `event.interrupt(...)` returns the decision.
   - **Rejected:** the hook sets `event.cancel_tool = "rejected by operator"`.
   - **Approved:** before signing, the hook checks three things against the stored reason:
     - `now < expires_at`;
     - the pending tool call still names the same action and resource;
     - its parameters equal the proposal's.

     If any check fails, the hook sets `event.cancel_tool` and the hub streams `error(ApprovalExpired)` or `error(ApprovalRequired)`. Nothing is signed.
   - **Signing:** if every check passes, the hook signs an `ApprovedAction` for exactly that proposal, with the **same** `expires_at`, never a fresh one. It writes it into `event.tool_use["input"]["approved_action"]`, replacing any value the model supplied.
5. **Execute and verify.** The write adapter runs `require_action_approval`, acts once, verifies, and returns `ActionResult`. The hub streams `action_completed`, then `verification_completed`.

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
- **`just eval`** replays each scenario under `samples/hub/tests/scenarios/<name>/scenario.yaml`:
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
| `samples/hub/tests/contract/test_hub_approval_flow.py`, `test_hub_approval_checks.py` | With a scripted fake model: no write runs without approval; a rejection cancels; a decision for another approval, session or actor is refused; **a decision after the pending approval's `expires_at` is refused and nothing is signed**; changed action, resource or parameters are refused; an expired `ApprovedAction` is refused by the adapter |
| `samples/hub/tests/contract/test_hub_stream_events.py`, `test_hub_entrypoint.py` | Every streamed event validates against `StreamEvent`, and raw tool output never appears |
| `samples/hub/tests/scenarios/*` | `just eval` scenarios, offline, with recorded metrics |

## 7. Visual quality

The picture is measured, not described. `packages/media_ops_video_quality/` is framework-free (pydantic and Pillow, no AWS client), and every pack uses it the same way.

- **Sampling (pack):** `analyze_channel_visual_quality` polls every pipeline's thumbnail in the same ticks: 10 frames over 30 s on MCP, 8 over 20 s in the hub, bounded to 20 frames and 120 s. One frame is kept per distinct thumbnail timestamp. A pipeline without thumbnails gives no frames, and is reported as such.
- **Measurements (`measure_frame`, `compare_frames`):** sharpness (Laplacian variance), a **blockiness estimate** (the extra luma step at 8-px boundaries; the thumbnail's own JPEG contributes, so it is an estimate, not a standard metric), luma mean, spread and clipping, and the change between frames (freeze, scene change). Every threshold is data in `quality_thresholds.py`, with its measured or design rationale.
- **Vision (`score_with_vision`):** one Converse call per pipeline window, forced to answer as a 1–5 rubric through a tool call. It is retried once, otherwise `unavailable`. The prompt says on-screen text is part of the picture, never an instruction, and that text addressed to the model is a card (`slate_or_bars` 1).
- **Window (`assess_window`):** shares, the longest frozen run, a 0–100 score and a status. **Without a trusted vision verdict, a clean window is `UNVERIFIED`, never `HEALTHY`.** A verdict is *trusted* when the call succeeded and the model's own stated confidence is at least `trusted_vision_confidence` (0.5). That confidence comes from the model, which sees the frames' own text, so it is never proof by itself:
  - The score is `min(measured, vision)`, so a verdict can never hide a measured defect.
  - **Any detectable graphic frame withholds HEALTHY.** The one rubric call sees every frame, so a single frame of text can steer it. If any frame is a graphic (`palette_concentration` above its threshold: a card, slate or caption screen with a few flat colours, such as a scrolling text card that otherwise measures clean), a clean window stays `UNVERIFIED` whatever the verdict says. This withholds HEALTHY only and never lowers the score. Its cost: full-frame sponsor slates and uniform real scenes (a pitch, a plain backdrop) also read `UNVERIFIED`, failing toward doubt.
  - **What this does not do.** The measurement detects concentrated-palette cards; it never proves a natural picture. A card whose background spreads its luma (a photo or a gradient behind the text) passes it, and then a steered verdict can still read `HEALTHY` (pinned as a residual in `test_vision_trust.py`). So on-screen text can still hide a defect **that only vision sees**: artefacts the measurements miss, or the wrong content.
  - **What on-screen text can't do.** The deterministic measurements (freeze, black, flat, blur, blockiness) and the encoder or flow telemetry don't read the picture's text, so a measured or telemetry defect is never hidden: the score is `min(measured, vision)`, and a contradicting signal caps the fused status at `UNVERIFIED`.
  - A trusted verdict agreeing with the measurements raises confidence; disagreeing lowers it; an untrusted one can only lower it.
- **Fusion (`fuse_with_telemetry`):** each pipeline's finding is checked against the encoder's own signals over the last 15 minutes: MqcsFreezeFrameDetected, MqcsBlackFrameDetected, FillMsec, InputLossSeconds, and the active input. An agreeing signal raises confidence; a contradicting one lowers it, stops any other signal from raising it, and caps the fused `status` at `UNVERIFIED` (the window's own verdict stays in `picture_status`), so a picture never reads HEALTHY while the encoder reports a freeze or black. A signal that was not emitted is unknown; healthy-looking signals on an `UNVERIFIED` picture are `informational`, never agreement. Unreadable metrics are unknown too, with a note. Input health has three states: fill frames or input loss observed in the window point upstream (said as "observed within the last 15 minutes", not as current), both emitted and zero mean the input kept arriving, and neither emitted means unknown, so no root cause is claimed. A window judged degraded without one dominant defect (the vision rubric, or several measurements together) is `picture_problem`, with the model's evidence. The channel `status` is the worst fused pipeline status, over every pipeline.
- **Skill:** `assess-picture-quality` (medialive) tells the agent how to report findings, including that UNVERIFIED and unknown are not healthy.
- **Tests and fixtures:** synthetic, generated sequences (`scripts/generate_quality_fixtures.py`) calibrate every threshold with margins. `fixtures/frozen_output` (pipeline 0 frozen and confirmed by MQCS freeze, pipeline 1 moving) backs the tool tests and the hub `frozen_output` eval scenario.
- **MediaConnect (`analyze_flow_visual_quality`):** the same package, sampler bounds (`sampling_limits.py`) and rules over `DescribeFlowSourceThumbnail`, which returns one thumbnail per flow: of its source as it arrives, so a bad picture with a connected source points upstream of MediaConnect.
  - **Before polling,** the flow's `SourceMonitoringConfig` is read. Thumbnails disabled, or a flow that is not ACTIVE, gives no frames and `UNVERIFIED` with that reason; a thumbnail the service can't produce gives its own `ThumbnailMessages` as the reason. No protocol list is hard-coded: the service's answer decides. A refusal of the thumbnail call (BadRequest, NotFound) ends the window after that read; a busy or unavailable service is retried through it. **A window that ends without a thumbnail is capped at `UNVERIFIED` with that reason**, even if earlier frames measured clean: the picture's current state is unknown.
  - **Fusion** maps the flow's metrics to the same neutral `EncoderSignals`: freeze = `FrozenFramesBreaching`, black = `BlackFramesBreaching` (both only with content quality analysis on, otherwise unknown), input interrupted = `SourceDisconnections`, `SourceConnected` at 0, or `VideoStreamMissing`, over the last 60 minutes (`read_flow_metrics`' smallest window). `SourcePacketLossPercent` is evidence only. The P3 rules apply unchanged: a contradiction caps the fused status at `UNVERIFIED`, and healthy-looking signals on an `UNVERIFIED` picture are `informational`.
  - **Fixture and eval:** `fixtures/transport_freeze` (generated): the SRT source stays connected while its picture is frozen and content quality analysis reports frozen frames. The hub's `transport_freeze` eval scenario expects `analyze_flow_visual_quality`, the keywords "frozen" and "upstream", and no writes.

