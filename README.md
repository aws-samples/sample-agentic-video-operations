<div align="center">
  <img src="./docs/images/genai.png" alt="Agentic Intelligent Media Operations" width="120">
  <h1>Agentic Intelligent Media Operations</h1>

  [![License](https://img.shields.io/badge/License-MIT--0-blue.svg)](https://github.com/aws/mit-0)
</div>

## Purpose

Investigate live-video transport, encoding, delivery, and viewer-experience
problems with focused AI-agent samples.

Choose the operator outcome you need:

| I want to… | Sample | Start with |
|---|---|---|
| Find regional buffering, bitrate, or playback-error patterns in CMCD data | [`cmcd`](samples/cmcd/) | `just run cmcd` |
| Inspect MediaConnect flow health, packet loss, metrics, or thumbnails | [`mediaconnect`](samples/mediaconnect/) | `just run mediaconnect` |
| Inspect MediaLive channels, inputs, outputs, schedules, or alarms | [`medialive`](samples/medialive/) | `just run medialive` |
| Investigate a signal path across MediaConnect and MediaLive, with approved fixes | [`hub`](samples/hub/) | `just demo` |
| Explore CDN and streaming analytics through a web application | [`hydrolix`](samples/hydrolix/) | `just deploy hydrolix` |

> [!IMPORTANT]
> These samples are for educational and reference purposes only. They are not
> intended for production use without security hardening, thorough testing,
> and customization for your environment.

## Try It First — No AWS Account

Three commands after cloning. No credentials, no `.env`, no cost:

```bash
uv tool install rust-just
just doctor
just smoke
```

```text
ok   cmcd             analyze_buffer_events
ok   mediaconnect     list_flows
ok   medialive        list_channels
Demo smoke passed without AWS clients.
```

Every sample just started as a real MCP server and answered from **fixtures** —
recorded AWS responses for scripted incidents (a MediaLive input loss, an SRT
packet-loss event, a viewer buffering spike). Nothing touched AWS.

Then watch the hub agent investigate a recorded incident, still offline:

```bash
just demo
```

It streams each tool call and ends with the diagnosis (impact, evidence, next
action) for a MediaLive channel whose pipeline 0 lost its SRT input.

From there, [`docs/walkthrough.md`](docs/walkthrough.md) takes you the rest of
the way in order of commitment: investigate a recorded incident from your own
MCP client (still no AWS account), run the hub agent locally against fixtures
(Bedrock only, cents per question), then deploy for real.

## Architecture

The samples cover two connected views of a live-video workflow: the upstream
signal path and the downstream delivery and viewer-experience path.

```mermaid
flowchart LR
    Source[Live source] --> MC[AWS Elemental MediaConnect]
    MC --> ML[AWS Elemental MediaLive]
    ML --> CDN[Content delivery]
    CDN --> Players[Video players]

    Hub[hub agent] --> MCPkg[mediaconnect pack]
    Hub --> MLPkg[medialive pack]
    MCPkg --> MC
    MLPkg --> ML

    Players --> CMCD[cmcd viewer QoE]
    CDN --> Hydrolix[hydrolix CDN analytics]
```

- `mediaconnect` and `medialive` expose focused operational tools.
- `hub` is one agent that loads both as domain packs, and asks an operator before any write.
- `cmcd` analyzes player telemetry stored in InfluxDB.
- `hydrolix` provides multi-agent CDN analytics with a web UI.

## Prerequisites

For the offline demo:

- Python 3.12 or newer (`uv` installs it automatically from `.python-version`).
- [`uv`](https://docs.astral.sh/uv/).
- [`just`](https://just.systems/), installed in the setup steps below.

For AWS-backed runs and deployments, also install:

- AWS CLI with configured credentials.
- Docker.
- Node.js 20 or newer; each CDK app installs its local AWS CDK with `npm ci`.
- Access to the selected Amazon Bedrock models.

Run the repository prerequisite check before starting:

```bash
just doctor
```

`just doctor` reports a fix command for each missing requirement. It fails only
when the offline group (`uv`, `just`, or Python) is incomplete; AWS, Docker,
Node.js, CDK, and bootstrap gaps are warnings.

Before an AWS-backed run or deployment, make those checks strict:

```bash
just doctor aws
```

### Models

Choose models once in the root `.env`. All local runs and deployments use the
same values.

| Role | Default | Used by | Change it |
|---|---|---|---|
| Reasoning agent | `us.anthropic.claude-sonnet-4-6` | The hub agent, Hydrolix agents | Edit `AGENT_MODEL_ID` in `.env` |
| Thumbnail vision | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | MediaLive and MediaConnect thumbnail adapters | Edit `THUMBNAIL_MODEL_ID` in `.env` |
| Chart generation | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Hydrolix web UI | Edit `CHART_MODEL_ID` in `.env` |

Override one deployment without editing `.env`:

```bash
AGENT_MODEL_ID=<model-id> just deploy <key>
```

A reasoning agent must not use a Haiku model.

## Setup and Run

### Run Locally

1. Clone the repository:

   ```bash
   git clone https://github.com/aws-samples/sample-agentic-video-operations.git
   cd sample-agentic-video-operations
   ```

2. Install `just`:

   ```bash
   uv tool install rust-just
   ```

3. Create local configuration:

   ```bash
   cp .env.example .env
   ```

4. Check prerequisites:

   ```bash
   just doctor
   ```

5. Prove every sample works offline:

   ```bash
   just smoke
   ```

6. Run the hub's offline investigation:

   ```bash
   just demo
   ```

Neither step needs an AWS account or a Bedrock call. `just smoke` starts each
sample's MCP server on recorded fixtures and calls one tool. `just demo` replays
a recorded MediaLive input-loss incident through the real hub and medialive pack
with a scripted model, and prints the diagnosis: pipeline 0 lost its SRT input.

Then follow [`docs/walkthrough.md`](docs/walkthrough.md): it connects a sample
to your MCP client on fixtures (no AWS account), runs the hub agent locally,
and only then deploys.

Run an individual sample's MCP server with:

```bash
just run <key>
```

Set `DEMO=1` for the fixture-backed run. See that sample's README for
configuration, MCP client setup, and a known-good request.

### Deploy to AWS

Deploy a sample with its existing CloudFormation or CDK material:

```bash
just deploy <key>
```

The command prints the AWS account and region and asks for confirmation.
Deployments create billable resources. Write permissions are disabled by
default; explicitly set `ALLOW_WRITES=true` only when they are required.

### Verify the Deployment

Follow the deployed verification request in the sample README. It provides an
exact request against the deployed endpoint and the expected operational result.

## Teardown

Stop a local process with `Ctrl+C`.

Destroy everything created by a sample deployment:

```bash
just destroy <key>
```

Confirm the related CloudFormation stacks and manually created media resources
are gone. Orphaned infrastructure can continue to incur cost.

## Known Limitations

- The repository contains educational samples, not a production platform.
- Security hardening, tenant isolation, quotas, and operational runbooks remain
  the adopter's responsibility.
- Model output is nondeterministic and must not replace operational policy.
- Some samples currently require AWS to demonstrate their complete use case;
  fixture-backed coverage is being added incrementally.
- Write operations require explicit enablement, approval, and verification.
- Supported regions and model availability depend on the selected AWS account.

## Development

Use the root commands:

```bash
just doctor
just doctor aws
just test <key>
just lint
just eval
```

Read [`AGENTS.md`](AGENTS.md) before changing code. Sample READMEs follow
[`docs/write_sample_readme.md`](docs/write_sample_readme.md).

## Contributing

Contributions are welcome. Keep changes focused, include offline tests, and
follow [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Security

Never commit `.env` files, credentials, account IDs, ARNs, or real resource
IDs. Report security issues using the process in
[`CONTRIBUTING.md`](CONTRIBUTING.md#security-issue-notifications).

## License

This project is licensed under the MIT No Attribution License. See
[`LICENSE`](LICENSE).
