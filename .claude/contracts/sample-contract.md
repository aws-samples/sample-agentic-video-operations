# Sample Contract

Every sample in this repo looks and runs the same way. A contributor who knows one sample knows them all.

This contract is the minimum bar. `../DEVELOPMENT_GUIDELINES.md` is the target. Where they disagree, this contract wins, because it encodes the user's "simplest first" requirement.

Enforces guidelines §1 (names), §2 (small files), §5 (layout, trimmed), §15 (configuration, imports), §16 (documentation).

## 1. Samples and their keys

The sample key is the argument to every `just` recipe.

| Key | Folder | Use case | Deploys with (existing material, unchanged) |
|---|---|---|---|
| `cmcd` | `cmcd-mcp-server/` | Viewer QoE from CMCD data in InfluxDB | `cloudfront-cmcd-kinesis.yaml` (CloudFormation) |
| `mediaconnect` | `mediaconnect-mcp-server/` | MediaConnect flow health and control | No own deploy. Runs in the cloud as the EMX specialist of `langchain` |
| `medialive` | `medialive-mcp-server/` | MediaLive channel health and control | `cdk/` (Strands agent on AgentCore) |
| `langchain` | `media-services-langchain/` | Coordinator + EML + EMX specialists on AgentCore | `cdk/` (3 runtimes) + `demo-channel.json` |
| `hydrolix` | `hydrolix-cdn-insights/` | CDN analytics with a web UI | Its existing CDK + Amplify |

Adding a sample means adding a row here, a folder that follows section 2, and its recipes in the `justfile`.

## 2. Folder layout (Python samples)

```
<folder>/
  pyproject.toml        # uv workspace member; pinned deps; one console script
  README.md             # sections in section 6
  .env.example          # the sample's variables to add to the root .env (safe placeholders)
  Dockerfile            # only if the sample ships a container
  src/<package>/
    entrypoints/        # transport only: serve_mcp.py, handle_agentcore_invocation.py
    adapters/<system>/  # one external action per file: describe_channel.py, stop_channel.py
    prompts/            # agents only; one prompt purpose per file
    settings/runtime_settings.py
  tests/
    unit/               # offline, no AWS credentials, no network
    scenarios/          # replays fixtures end to end (agents)
  cdk/ | *.yaml         # existing deploy material stays where it is
```

| Folder | Package | Console script |
|---|---|---|
| `cmcd-mcp-server` | `cmcd_mcp` | `serve-cmcd` |
| `mediaconnect-mcp-server` | `mediaconnect_mcp` | `serve-mediaconnect` |
| `medialive-mcp-server` | `medialive_mcp` | `serve-medialive` |
| `media-services-langchain` | `media_iops` | `serve-langchain` |

**Rules:**
- Package names MUST be unique across the repo. There MUST NOT be a top-level `tools`, `src` or `shared` package.
- File and function names follow guidelines §1: `verb_object`. No `utils.py`, `helpers.py`, `manager.py`, `service.py`, `tools.py`, `prompts.py`.
- A sample MUST NOT import another sample's internals through relative paths, `sys.path` changes or Docker `COPY`. It declares a workspace dependency instead:

  ```toml
  [tool.uv.sources]
  medialive-mcp-server = { workspace = true }
  ```
- A Dockerfile builds with `uv sync --frozen --package <folder>`. It MUST NOT `COPY` sibling sample folders. It MAY copy the workspace root files (`pyproject.toml`, `uv.lock`) plus the member folders it depends on, through uv.
- `hydrolix` (TypeScript CDK + React) follows only sections 4–6.

## 3. Repo root

```
pyproject.toml        # [tool.uv.workspace] members = the Python samples + media_ops_contracts
uv.lock               # one lock for the whole repo
justfile              # the only command entry point
scripts/check_prerequisites.py
media_ops_contracts/  # shared contract code (see tool-contract.md)
fixtures/<scenario>/  # the only fixture location; scenarios are shared across samples (one source of truth)
AGENTS.md             # one page: what is where, links to these contracts
.github/workflows/ci.yml
```

If two members cannot share one lock (a dependency conflict), the member is excluded from the workspace and gets its own `uv.lock`. Record the reason in its README.

## 4. Commands (`justfile`)

Install `just` once with `uv tool install rust-just`. Running `just` with no arguments lists the recipes.

| Recipe | Meaning | Native command it wraps |
|---|---|---|
| `just doctor` | Check prerequisites, printing a fix command for each failure | `uv run scripts/check_prerequisites.py` |
| `just run <key>` | Run the sample locally (MCP stdio or local agent server) | `uv run --package <folder> serve-<key>` |
| `just test [key]` | Offline unit and scenario tests | `uv run pytest <folder>/tests` |
| `just lint` | ruff check + format check | `uv run ruff check . && uv run ruff format --check .` |
| `just eval` | Replay the fixture scenarios and score them | `uv run pytest -m eval` |
| `just demo` | Coordinator on fixtures, with no AWS account | `DEMO=1 uv run --package media-services-langchain demo` |
| `just deploy <key>` | Deploy with the sample's existing material | per sample, see section 1 |
| `just destroy <key>` | Remove everything `deploy` created | per sample |
| `just demo-channel create\|delete` | Create or delete the MediaLive channel from `demo-channel.json` | `aws medialive create-channel --cli-input-json …` |

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

**Names that are retired**, replaced by the shared ones above:
- `BEDROCK_AGENTCORE_MEMORY_ID` → `MEMORY_ID`.
- `MEDIALIVE_DEFAULT_CHANNEL_ID` and `MEDIALIVE_TEST_CHANNEL_ID` → `MEDIALIVE_CHANNEL_ID`.

Sample-specific variables keep their current names: `INFLUXDB_URL`, `INFLUXDB_TOKEN`, `INFLUXDB_ORG`, `VERIFY_SSL` (default now `true`), `HYDROLIX_*`, `MEDIACONNECT_FLOW_ARN`, `MEDIALIVE_CHANNEL_ID`.

**One root `.env`.** `just` loads only the root `.env` (`set dotenv-load`). A sample's `.env.example` lists the variables to add there, and the sample never reads its own `.env`. Settings read the process environment only.

`.env` is never committed. `.env.example` is always committed.

### Model selection (every deployment)

The user chooses models **once**, in the root `.env`. Every `just run` and `just deploy` uses that choice. No model id is hardcoded anywhere else.

| Role | Env var | CDK parameter | Default | Used by |
|---|---|---|---|---|
| Reasoning agent | `AGENT_MODEL_ID` | `BedrockModelId` | `us.anthropic.claude-sonnet-4-6` | langchain coordinator, EML, EMX · medialive Strands agent · hydrolix orchestrator and its 3 sub-agents · `cmcd` client script |
| Thumbnail vision | `THUMBNAIL_MODEL_ID` | `ThumbnailModelId` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | medialive and mediaconnect thumbnail adapters (and so EML/EMX) |
| Chart generation | `CHART_MODEL_ID` | Amplify build env | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | hydrolix web UI only |

**Rules:**
- Every CDK stack exposes the same parameter names and passes the same env var names into the runtime.
  - Hydrolix's `BEDROCK_MODEL_ID` is renamed to `AGENT_MODEL_ID`.
  - Each `just deploy <key>` passes `--parameters BedrockModelId="$AGENT_MODEL_ID"` (and `ThumbnailModelId` where it exists).
- **Defaults live in exactly two places:** the root `.env.example`, and the CDK parameter default, which must match it. Python reads the value through settings and has no fallback model ids.
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
  - *Run Locally* comes first. Use `DEMO=1` where fixtures exist, so it needs no AWS account.
  - *Deploy to AWS* uses `just deploy <key>`.
  - Include one known-good request and its expected result.
- **MCP samples:** also include the `mcp.json` snippet, plus a Tools table with three columns: tool, read/write, what it does.
- **Teardown:** `just destroy <key>`, plus every manual cleanup step, such as `just demo-channel delete`.
- **Detail beyond the first run** goes in `docs/<action_name>.md` (§16 "Supporting documentation").

## 7. Done when (for any sample change)

- `just test <key>` and `just lint` pass offline.
- `just eval` passes, for samples with scenarios.
- The deploy material validates: `cdk synth`, or `aws cloudformation validate-template`.
- The README meets section 6 and the §16 "Documentation definition of done". The reviewer ran the primary setup-and-run path.
