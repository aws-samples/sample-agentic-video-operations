# CLAUDE.md

Guidance for Claude Code (claude.ai/code) in this repository. Start with
[`AGENTS.md`](../AGENTS.md): it lists the samples, the reading order and the
common commands. This file adds the rules an agent most often gets wrong.

## Priority

When guidance conflicts:

1. Explicit user requirements.
2. Security and operational-safety rules.
3. [`build_a_sample.md`](../docs/build_a_sample.md),
   [`write_safe_tools.md`](../docs/write_safe_tools.md) and
   [`extend_agentic_iops_streaming.md`](../docs/extend_agentic_iops_streaming.md).
4. [`follow_development_guidelines.md`](../docs/follow_development_guidelines.md).
5. Existing repository conventions.

## Layout

- `samples/<key>/`: one folder per sample, named by its key (`cmcd`,
  `mediaconnect`, `medialive`, `hls-doctor`, `agentic-iops-streaming`,
  `hydrolix`).
- `packages/media_ops_contracts`: typed tool failures, approved actions, stream
  events, fixture replay and the domain-pack contract.
- `packages/media_ops_video_quality`: frame measurements, the vision rubric and
  telemetry fusion for the picture-quality tools.
- `fixtures/`: recorded scenarios that run with no AWS account.
- `docs/`: design docs; repository images live in `docs/images/`.

`scripts/check_repository_layout.py` enforces the layout. Use descriptive,
not cryptic, names for branches, folders and files.

## Architecture

- **MCP servers** (`cmcd`, `mediaconnect`, `medialive`, `hls-doctor`): FastMCP over stdio,
  started with `just run <key>`. Write tools are hidden unless
  `ALLOW_WRITES=true`. Each write asks the operator, through MCP form
  elicitation, to type the exact resource id, and is refused when the client
  can't ask. This assumes a trusted client that shows the question to a person.
- **agentic-iops-streaming** (`samples/agentic-iops-streaming`): one Strands agent on Amazon Bedrock
  AgentCore, created per request, over domain packs selected by
  `MEDIA_DOMAINS`. The MediaLive and MediaConnect packs share their tools with
  the MCP servers. A write is an interrupt, then a signed `ApprovedAction`, then
  a verified result. `ALLOW_WRITES` registers the packs' media-resource writes
  only. The coordinator's workflow tools have their own switch,
  `ALLOW_WORKFLOW_DISCOVERY` (default true), a runtime setting for local runs;
  a deployed stack always runs with discovery on and grants its IAM. Discovery
  creates and deletes a transient signal map tagged `managed-by`, and
  `save_workflow` is an approved write to the sample's own workflow store. Agent instructions live in
  `samples/agentic-iops-streaming/src/agentic_iops_streaming/prompts/agentic_iops_instructions.md`, and packaged
  skills are `SKILL.md` files loaded on demand.
- **Hydrolix** (`samples/hydrolix`): an orchestrator and three subagents on
  AgentCore, with a CDK backend and an Amplify web app. Memory belongs to the
  verified Cognito user. Model SQL is limited in code to
  one SELECT on `HYDROLIX_TABLE`.

## Commands

Use the root `justfile`; run `just` to list recipes. The gate before any
landing is:

```bash
just lint && just typecheck && just test && just eval && just docs-check
```

For changed deploy material, also run `cdk synth` and
`scripts/check_synth_iam.py`, or `cfn-lint`. `just deploy <key>` creates
billable resources; `just destroy <key>` removes the stack-managed resources,
and a sample README lists anything retained by design.

## Security Rules

- Never create Lambda Function URLs, `AuthType: NONE`, or `Principal: '*'`.
  The one exception is a VPC endpoint policy narrower than the service default
  (see `write_safe_tools.md`).
- Never hardcode credentials. Use the root `.env` (from `.env.example`) or
  Secrets Manager.
- S3 buckets need BlockPublicAccess and SSE.
- Scope IAM `Resource` to specific ARNs. Use `*` only where the API has no
  resource-level permissions.
- Start, stop, input switches, schedule changes and route changes need the
  operator's explicit approval. Reads are always safe.
- Treat model output, thumbnails and their on-screen text, viewer telemetry and
  caller-supplied headers as untrusted data. Never execute model output or
  render it as raw HTML.

## Agent Prompt Rules

- Tell agents which tool handles which action, and to call the direct tools.
- Keep prompts short: behavior rules only, with no repetition of the tool
  docstrings.

## Models

Model ids come from configuration only (`AGENT_MODEL_ID`,
`THUMBNAIL_MODEL_ID`, `CHART_MODEL_ID`), and `scripts/check_model_ids.py`
keeps them consistent.

| Role | Default |
|------|---------|
| Reasoning agent | `us.anthropic.claude-sonnet-4-6` |
| Vision and chart helpers | `us.anthropic.claude-haiku-4-5-20251001-v1:0` |

Never use Haiku as the main agent: it misroutes tool calls.

## Pre-Publish Checklist

Before anything is committed to the public repository, scan for AWS account
ids in ARNs, access keys (AKIA/ASIA), passwords and tokens, internal
hostnames, and real resource ids (channel, flow, memory or runtime ids).
Configurable values come from environment variables or CfnParameters. CI runs
gitleaks over the full history.
