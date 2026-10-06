# Changelog

All notable changes to this repository are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

The samples are not versioned packages, so changes are grouped by release
candidate branch (`release-candidate/<name>-<date>`). The latest candidate is at
the top.

## [Unreleased]

Work merged after the latest release candidate. It moves into a candidate
section when the next candidate is cut.

## [media-ops-samples-2026-10-06] — release candidate, update 2 (release blockers)

Branch: `release-candidate/media-ops-samples-2026-10-06`. Pushed after the
review of the first cut. The release blockers from that review are fixed.

### Added
- **Hub deploy:** `just deploy hub` and `just destroy hub` for the Strands
  media ops hub on AgentCore, with a CDK app, an approval signing key in
  Secrets Manager and an invoke policy scoped to one caller role.
- **Offline evaluation:** `just eval` runs five scripted scenarios through
  the hub against recorded fixtures. It checks tool choice, forbidden
  tools, the tool-call budget, approvals and verified writes.
- **CI on release candidates:** typecheck, gitleaks over the full history,
  hadolint, an arm64 `docker build` for every Dockerfile, a build-context
  probe with planted secrets, and an IAM gate on the default CDK synth.
  Dependabot and pre-commit are configured.
- **Docs checks:** `just docs-check` fails when a doc names a command,
  recipe or file that doesn't exist, or describes planned work as shipped.
  It also checks that model ids come from one source.
- **Zero-AWS walkthrough:** `docs/walkthrough.md` goes from the recorded
  demo to a deployed sample. The README leads with `just smoke` and
  `just demo`.
- `SECURITY.md`, plus issue and pull request templates.

### Changed
- **MediaLive metrics** query each metric with its real dimensions,
  including `OutputGroupName` and `AudioDescriptionName`, and use the right
  statistic for each one. A metric that MediaLive doesn't emit for the
  channel is reported as not emitted, not as healthy.
- **CMCD** deploys through an account-owned artifacts bucket, because the
  template exceeds the inline size limit.

### Fixed
- **CMCD teardown** keeps the custom resource's network egress until the
  resource has responded, so destroy no longer hangs.
- **Docs** no longer describe recipes, paths or features that don't exist.
- **Hydrolix MCP pin:** `just deploy hydrolix` and the CI image build
  fetch mcp-hydrolix v0.3.7 (`b180404`). The previous pin named a commit
  that doesn't exist upstream. The runtime requirements now carry that
  release's dependency ranges, including `sqlglot` and `prometheus-client`,
  and keep `fastmcp` below 3.5 and `mcp` below 2.

### Security
- **IAM gate:** the default synth may not grant media writes, IAM changes,
  ECR push, workload access tokens, `iam:PassRole` or `sts:AssumeRole` on
  `*`, or whole-service actions. Matching ignores case. Telemetry and
  own-memory writes are allowed only on the app's own resource ARNs.
- **Hydrolix runtime role:** no ECR push or workload-token grants. Memory
  and DynamoDB access are scoped to the stack's own memory and table.
- **Hub runtime role:** memory and log access are scoped to its own memory
  and runtime log groups.
- **Docker build contexts** exclude `.env`, `.claude`, `.git` and `cdk.out`.
- **CMCD VPC endpoint:** S3 access from the private subnets is limited to
  the stack's own buckets and the CloudFormation response bucket.
- **Secret scan:** the one historical finding is a placeholder
  (`<INFLUX_DB_TOKEN>`), allowlisted by its exact fingerprint.

### Removed
- **Legacy LangChain hub** (coordinator, EML and EMX agents), the MediaLive
  bridge agent and their CDK. The Strands hub replaces them.

## [media-ops-samples-2026-10-06] — release candidate, first cut

Branch: `release-candidate/media-ops-samples-2026-10-06`.

### Added
- **One entry point for every sample:** `just` recipes `doctor`, `run`,
  `test`, `lint`, `smoke`, `docs-check`, `eval`, `demo`, `deploy` and
  `destroy`, with the native command each recipe wraps documented in the
  sample README.
- **`media_ops_contracts`:** a shared package for typed tool failures,
  approved actions, stream events, recorded-fixture replay and domain packs.
- **Recorded incident scenarios** that run with no AWS account:
  `input_loss` (MediaLive), `srt_packet_loss` (MediaConnect),
  `cmcd_rebuffering` (CMCD) and `no_input`.
- **Media ops hub** (`samples/hub`): one Strands agent on Amazon Bedrock
  AgentCore over pluggable domain packs selected by `MEDIA_DOMAINS`.
  - MediaLive and MediaConnect packs share their tools with the MCP servers.
  - Packaged skills are loaded on demand.
  - Writes need an explicit approval: interrupt, signed approval, then a
    verified action.
  - Stream events are delivered progressively.
- **CMCD:** `just deploy cmcd` and `just destroy cmcd` around the existing
  CloudFormation template.
  - Deploy creates bucket-scoped InfluxDB read and write tokens.
  - `just cmcd-token` writes the read token into `.env`.
  - A post-deploy write and read check confirms the pipeline works.
- **Hydrolix:** `just deploy hydrolix` and `just destroy hydrolix`.
- **CI:** lint, offline tests, documentation and repository-layout checks,
  `cdk synth` and `cfn-lint`.
- **Design docs** in `docs/`: building a sample, writing safe tools,
  extending the hub, and the development guidelines.

### Changed
- **Repository layout:** samples live in `samples/<key>/`, the shared
  package in `packages/`, and repository images in `docs/images/`. A layout
  check keeps it that way.
- **MCP servers:** each one is a uv package with typed adapters, classified
  AWS errors and offline tests. Write tools are hidden unless
  `ALLOW_WRITES=true`, and an approval is still required to use them.
- **Configuration:** settings come from one root `.env`. Model ids come from
  configuration only (`AGENT_MODEL_ID`, `THUMBNAIL_MODEL_ID`).
- **MediaLive health scoring:** severity scales with magnitude, and the
  overall status follows the worst finding. Both pipelines are read.
- **MediaConnect:** metrics use the right statistic for each metric.

### Fixed
- **Demo mode** fails closed and never creates AWS clients, even with a
  populated `.env`.
- **CMCD:**
  - The processing Lambda now authenticates to InfluxDB. Write failures
    surface instead of being dropped.
  - Teardown deletes the retained InfluxDB instance first, can be re-run
    after a partial failure, and lists anything left behind.
  - The CloudFormation template deploys through an account-owned artifacts
    bucket, because it exceeds the inline size limit.
- **MediaLive:** channel logs are read from the `ElementalMediaLive` log
  group, newest first.
- **Issue fixes:** items from
  [#25](https://github.com/aws-samples/sample-agentic-video-operations/issues/25),
  including `verify_ssl`, the memory variable names, the CMCD startup and
  buffer-starvation fields, and Dockerfile version pins.

### Security
- **CMCD credentials:** the InfluxDB token is no longer a tool parameter,
  Flux values are escaped, the raw Flux tool is removed, and the bastion
  helper no longer prints the password.
- **Least privilege:** each pack declares its own read and write IAM, and
  writes are granted only on explicit opt-in.
- **Hub isolation:** the hub refuses deployed requests without an actor or
  session.
- **Player:** the deployed CMCD player pins hls.js with Subresource
  Integrity.

### Removed
- Tracked `.env` files and hardcoded model ids.

### Known limitations
- The legacy LangChain coordinator code still sits under `samples/hub/`. It
  is being replaced by the hub, and its deployment is not supported
  (removed in update 2).
- `just eval` runs scripted scenarios offline; real-model evaluation is
  opt-in.
