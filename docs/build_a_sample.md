# Sample Contract

Every sample in this repo looks and runs the same way. A contributor who knows one sample knows them all.

This contract is the minimum bar. `follow_development_guidelines.md` is the target. Where they disagree, this contract wins, because it encodes the "simplest first" rule.

Enforces guidelines §1 (names), §2 (small files), §5 (layout, trimmed), §15 (configuration, imports), §16 (documentation).

## 1. Samples and their keys

The sample key is the argument to every `just` recipe.

**The folder is the key:** every sample lives in `samples/<key>/` (§3).

| Key | Use case | Deploys with (existing material) | Former folder |
|---|---|---|---|
| `cmcd` | Viewer QoE from CMCD data in InfluxDB | `cloudfront-cmcd-kinesis.yaml` (CloudFormation) | `cmcd-mcp-server/` |
| `mediaconnect` | MediaConnect flow health and control | No own deploy. Runs in the cloud as a domain pack of `agentic-iops-streaming` | `mediaconnect-mcp-server/` |
| `medialive` | MediaLive channel health and control | No own deploy. Runs in the cloud as a domain pack of `agentic-iops-streaming`; its former `cdk/` is now agentic-iops-streaming's | `medialive-mcp-server/` |
| `agentic-iops-streaming` | One agent that investigates across the selected media domains (extend_agentic_iops_streaming.md) | `samples/agentic-iops-streaming/cdk/` | consolidates the earlier multi-runtime sample |
| `hydrolix` | CDN analytics with a web UI | Its existing CDK + Amplify | `hydrolix-cdn-insights/` |

Adding a sample means adding a row here, a `samples/<key>/` folder that follows section 2, and its recipes in the `justfile`.

## 2. Folder layout (Python samples)

```
samples/<key>/
  pyproject.toml        # uv workspace member; pinned deps; one console script
  README.md             # sections in section 6
  Dockerfile            # only if the sample ships a container
  src/<package>/
    entrypoints/        # transport only: serve_mcp.py, handle_agentcore_invocation.py
    adapters/<system>/  # one external action per file: describe_channel.py, stop_channel.py
    domain/             # when needed: typed rules and records; no SDK/framework imports
    workflows/          # when needed: application actions that coordinate adapters
    tool_surface/       # domain packs: shared read/write tool factories
    skills/             # domain packs/agents: one purpose per SKILL.md
    prompts/            # agents only: one prompt purpose per file
    settings/runtime_settings.py
    domain_pack.py      # domain packs only; exposes the shared tool surface
  tests/
    unit/               # offline, no AWS credentials, no network
    pack/               # domain-pack contract and IAM coverage
    scenarios/          # replays fixtures end to end (agents)
  iam_permissions.json  # domain packs only: IAM agentic-iops-streaming grants for this pack (extend_agentic_iops_streaming.md §1)
  docs/                 # optional; the sample's own images go in docs/images/
  cdk/ | *.yaml         # existing deploy material stays where it is
```

| Folder | Distribution | Package | Console script |
|---|---|---|---|
| `samples/cmcd` | `cmcd-mcp-server` | `cmcd_mcp` | `serve-cmcd` |
| `samples/mediaconnect` | `mediaconnect-mcp-server` | `mediaconnect_mcp` | `serve-mediaconnect` |
| `samples/medialive` | `medialive-mcp-server` | `medialive_mcp` | `serve-medialive` |
| `samples/agentic-iops-streaming` | `agentic-iops-streaming` | `agentic_iops_streaming` | `serve-agentic-iops-streaming` |
| `packages/media_ops_contracts` | `media-ops-contracts` | `media_ops_contracts` | none |

**Rules:**
- Package names MUST be unique across the repo. There MUST NOT be a top-level `tools`, `src` or `shared` package.
- File and function names follow guidelines §1: `verb_object`. No `utils.py`, `helpers.py`, `manager.py`, `service.py`, `tools.py`, `prompts.py`.
- A sample MUST NOT import another sample's internals through relative paths, `sys.path` changes or Docker `COPY`. It declares a workspace dependency instead:

  ```toml
  [tool.uv.sources]
  medialive-mcp-server = { workspace = true }
  ```
- A Dockerfile builds with `uv sync --frozen --package <distribution>`. It MUST NOT `COPY` sibling sample folders. It MAY copy the workspace root files (`pyproject.toml`, `uv.lock`) plus the member folders it depends on, through uv.
- `hydrolix` (TypeScript CDK + React) follows only sections 4–6.

## 3. Repo root (guidelines §20)

The root holds only these entries. `scripts/check_repository_layout.py`, run by `just docs-check` and CI, enforces the list.

```
README.md  AGENTS.md  CHANGELOG.md  CONTRIBUTING.md  CODE_OF_CONDUCT.md  LICENSE
justfile  pyproject.toml  uv.lock  .env.example  .python-version  .gitignore
.gitleaksignore  .pre-commit-config.yaml  .dockerignore
.github/workflows/ci.yml
.claude/              # Claude Code instructions; .claude/plans/ is never tracked
docs/                 # repo-level documentation; repo-level images in docs/images/
samples/<key>/        # one folder per sample (§1, §2)
packages/media_ops_contracts/   # shared contract code (write_safe_tools.md §5)
fixtures/<scenario>/  # the only fixture location; scenarios are shared across samples
scripts/              # repo tooling: check_prerequisites.py, check_*.py, manage_*_stack.py
```

**Rules:**
- **Images** are any file with an image extension, or anything in a folder named `images/`. They live only in:
  - `docs/images/` (repo);
  - `samples/<key>/docs/images/` (sample);
  - a web app's own `public/` or `src/`. A web app is a folder with a tracked `package.json` and a `public/`; CDK apps aren't web apps.
- **Nothing under `.claude/plans/` is tracked.** Handoff, review and plan files stay in each builder's clone.
- **Workspace:** `pyproject.toml` lists `samples/*` and `packages/*` members explicitly, and the root project depends on each member, so `uv sync` installs them all.

If two members cannot share one lock (a dependency conflict), the member is excluded from the workspace and gets its own `uv.lock`. Record the reason in its README.

## 4. Commands (`justfile`)

Install `just` once with `uv tool install rust-just`. Running `just` with no arguments lists the recipes.

| Recipe | Meaning | Native command it wraps |
|---|---|---|
| `just doctor` | Check prerequisites, printing a fix command for each failure | `uv run python scripts/check_prerequisites.py` |
| `just smoke` | Start each converted MCP server on fixtures and make one read | `uv run python scripts/smoke_demo_servers.py` |
| `just smoke aws` | Run one live list and health read per converted MCP sample | `uv run python scripts/smoke_aws_servers.py` |
| `just docs-check` | README structure, repository layout, documentation claims and model ids | `uv run python scripts/check_readme_structure.py && uv run python scripts/check_repository_layout.py && uv run python scripts/check_docs_claims.py && uv run python scripts/check_model_ids.py` |
| `just run cmcd\|mediaconnect\|medialive` | Run one MCP stdio server | `uv run --package <distribution> serve-<key>` |
| `just run agentic-iops-streaming` | Run the agentic-iops-streaming server locally | `AGENTIC_IOPS_LOCAL_MODE=true uv run --package agentic-iops-streaming serve-agentic-iops-streaming` |
| `just test` | All offline unit and scenario tests, except those that start real processes | `uv run pytest` |
| `just test-slow` | The tests that start real processes (MCP servers, a hung server the deadline must kill); CI runs them | `uv run pytest -m slow` |
| `just test contracts` | Shared contract tests | `uv run pytest packages/media_ops_contracts/tests` |
| `just test cmcd` | CMCD tests | `uv run pytest samples/cmcd/tests` |
| `just test mediaconnect` | MediaConnect tests | `uv run pytest samples/mediaconnect/tests` |
| `just test medialive` | MediaLive scenario and pack tests | `uv run pytest samples/medialive/tests/scenarios samples/medialive/tests/pack` |
| `just test agentic-iops-streaming` | Contract tests of agentic-iops-streaming | `uv run pytest samples/agentic-iops-streaming/tests/contract` |
| `just test hydrolix` | Hydrolix deployment-management tests | `uv run pytest scripts/tests/test_manage_hydrolix_stack.py` |
| `just lint` | ruff check + format check | `uv run ruff check . && uv run ruff format --check .` |
| `just typecheck` | Static type check with the repository ratchet | `uv run mypy` |
| `just eval` | Replay the fixture scenarios and score them | `uv run pytest -m eval` |
| `just demo` | The agent on fixtures, with no AWS account | `uv run --package agentic-iops-streaming demo-agentic-iops-streaming` |
| `just cmcd-token` | Create or reuse a CMCD bucket-read token | `uv run python scripts/manage_cmcd_stack.py create-read-token` |
| `just cmcd-token-verify` | Verify that the CMCD token can read but cannot write | `uv run python scripts/verify_influxdb_read_token.py` |
| `just deploy <key>` | Deploy with the sample's existing material | per sample, see section 1 |
| `just destroy <key>` | Remove everything `deploy` created | per sample |

**Rules:**
- A recipe is a thin wrapper. It contains no logic beyond choosing the native command and passing `.env` values. Logic belongs in a script or in the sample.
- The sample README shows the raw native command under each recipe, so nothing is hidden.
- `deploy` and `destroy` MUST print the AWS account and region and ask for confirmation, unless `--yes` is passed.
- `deploy` defaults to read-only permissions. Write permissions require `ALLOW_WRITES=true` at deploy time.

## 5. Configuration

`settings/runtime_settings.py` holds a `pydantic-settings` class that reads the environment once at startup and fails with the name of any missing variable. Business code receives the settings object. It never calls `os.getenv`.

**Shared names.** These are the names already used most in the repo:

| Variable | Default | Meaning |
|---|---|---|
| `AWS_REGION` | none (required) | Region for every AWS client |
| `AGENT_MODEL_ID` | `us.anthropic.claude-sonnet-4-6` | Bedrock model for agents |
| `THUMBNAIL_MODEL_ID` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Bedrock model for thumbnail analysis (MediaLive and MediaConnect) |
| `MEMORY_ID` | empty, meaning memory is off | AgentCore Memory id |
| `ALLOW_WRITES` | `false` | Register write tools, or grant write IAM at deploy |
| `DEMO` | `false` | Replay fixtures instead of calling AWS |
| `DEMO_SCENARIO` | per sample | Which `fixtures/<scenario>/` to replay |
| `FIXTURES_DIR` | `fixtures` (relative to the repo root, where `just` runs) | Fixture root override |
| `APPROVAL_SIGNING_KEY` | random per process locally; from Secrets Manager when deployed | HMAC key for `ApprovedAction` |
| `MEDIA_DOMAINS` | `medialive,mediaconnect` | Domain packs the coordinator loads (extend_agentic_iops_streaming.md §2) |

**Names that are retired**, replaced by the shared ones above:
- `BEDROCK_AGENTCORE_MEMORY_ID` → `MEMORY_ID`.
- `MEDIALIVE_DEFAULT_CHANNEL_ID` and `MEDIALIVE_TEST_CHANNEL_ID` → `MEDIALIVE_CHANNEL_ID`.

Sample runtime variables keep their current names: `INFLUXDB_URL`, `INFLUXDB_TOKEN`, `INFLUXDB_ORG`, `VERIFY_SSL` (default now `true`), `HYDROLIX_*`, and `MEDIALIVE_CHANNEL_ID`. The live AWS smoke script also requires `MEDIACONNECT_FLOW_ARN` to choose the flow it probes; MediaConnect tools themselves require `flow_arn` in each applicable call.

**One root `.env`.** `just` loads only the root `.env` (`set dotenv-load`).
A script under `scripts/` that reads settings calls `load_root_env(os.environ)` at entry
(`scripts/read_root_env.py`), so its raw `uv run python scripts/...` command reads the
same file; values already in the environment win, as with `just`. A missing setting
names the file that was read.
The root `.env.example` is the only configuration template: shared defaults
are active, and each sample's optional settings live in a clearly labelled,
commented section. A sample README tells the user which section to uncomment.
Samples MUST NOT add their own `.env` or `.env.example`; settings read the
process environment only.

The root `.env` is never committed. The root `.env.example` is always committed.

### Model selection (every deployment)

The user chooses models **once**, in the root `.env`. Every `just run` and `just deploy` uses that choice. No model id is hardcoded anywhere else.

| Role | Env var | CDK input | Default | Used by |
|---|---|---|---|---|
| Reasoning agent | `AGENT_MODEL_ID` | `-c agentModelId` (hydrolix: the default of its `BedrockModelId` parameter) | `us.anthropic.claude-sonnet-4-6` | agentic-iops-streaming · hydrolix orchestrator and its 3 sub-agents |
| Thumbnail vision | `THUMBNAIL_MODEL_ID` | `-c thumbnailModelId` (agentic-iops-streaming only) | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | medialive and mediaconnect thumbnail adapters (in the MCP servers and agentic-iops-streaming) |
| Chart generation | `CHART_MODEL_ID` | Amplify build env | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | hydrolix web UI only |

**Rules:**
- Every CDK stack passes the same env var names into the runtime.
  - Hydrolix's `BEDROCK_MODEL_ID` is renamed to `AGENT_MODEL_ID`.
  - Both deploys pass the models as CDK context (`-c agentModelId=...`, and for agentic-iops-streaming `-c thumbnailModelId=...`) to the security diff and to the deploy alike, because `cdk diff` takes no `--parameters` and the diff shown before approval must synthesize the same template as the deploy. Each stack derives the foundation model from the profile id.
  - The agentic-iops-streaming stack writes the models into its IAM directly. Hydrolix keeps its `BedrockModelId` parameter, whose default the context sets; `just deploy hydrolix` passes `--no-previous-parameters`, so an existing stack takes that default instead of its last value. Its security diff shows the grant as a reference to the parameter, so the confirmation also names the model ("Bedrock model granted").
- **Defaults live in exactly two places:** the root `.env.example`, and the CDK default (parameter or context), which must match it. Python reads the value through settings and has no fallback model ids.
- **One id rule:** `scripts/model_id_rule.json` defines a valid id: a bare `provider.model`, or a cross-Region profile `<prefix>.provider.model`. The deploy scripts check `AGENT_MODEL_ID` (and agentic-iops-streaming's `THUMBNAIL_MODEL_ID`) with it before anything is installed, built or diffed, and both CDK stacks enforce the same file at synth or deploy.
- **A reasoning agent never runs on Haiku** (`.claude/CLAUDE.md` "Model Selection"). Haiku is only for the thumbnail and chart roles.
- **To switch models for one deploy,** set the variable on the command: `AGENT_MODEL_ID=<id> just deploy hydrolix`.
- **Before any deploy, `just doctor` checks access** to `AGENT_MODEL_ID` and `THUMBNAIL_MODEL_ID` in `AWS_REGION`.
- **The root README has a "Models" table:** role, default, where it is used, and how to change it.

## 6. README (every sample)

Follow guidelines §16 exactly. Use its skeleton and section order:
1. Purpose
2. Architecture (with a Mermaid diagram)
3. Prerequisites
4. Setup and Run (Run Locally · Deploy to AWS · Verify the Deployment)
5. Teardown
6. Known Limitations
7. Development
8. Contributing
9. Security
10. License

**What this contract adds to §16:**
- **Setup and Run:** the primary path is `just` recipes, with the raw native command shown under each.
  - *Run Locally* comes first, and its first numbered step is exactly
    `cp .env.example .env` from the repository root.
  - Use `DEMO=1` where fixtures exist, so it needs no AWS account.
  - *Deploy to AWS* uses `just deploy <key>`.
  - Include one known-good request and its expected result.
- **MCP samples:** also include the `mcp.json` snippet, plus a Tools table with three columns: tool, read/write, what it does.
- **Teardown:** `just destroy <key>`, plus every manual cleanup step the sample needs.
- **Detail beyond the first run** goes in `docs/<action_name>.md` (§16 "Supporting documentation").

## 7. Done when (for any sample change)

- `just test <key>` and `just lint` pass offline.
- `just eval` passes, for samples with scenarios.
- The deploy material validates: `cdk synth`, or `aws cloudformation validate-template`.
- The README meets section 6 and the §16 "Documentation definition of done". The reviewer ran the primary setup-and-run path.
