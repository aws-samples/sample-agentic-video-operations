# MediaConnect MCP Server

Investigate live-video transport health, packet loss, connectivity, and visual
evidence from an MCP-compatible assistant.

> [!IMPORTANT]
> This AWS sample is for educational and reference purposes. It requires
> security hardening, testing, and customization before production use.

## Purpose

Use this sample when an operator needs to determine whether an incident begins
in contribution or distribution transport before investigating downstream
encoding and delivery.

The first successful run needs no AWS account. It replays an SRT incident where
the MediaConnect flow remains active and connected while packet loss,
retransmission recovery, and unrecovered packets rise.

## Architecture

```mermaid
flowchart LR
    Operator --> Client[MCP-compatible client]
    Client --> Server[MediaConnect MCP server]
    Server -->|demo| Fixtures[Recorded AWS responses]
    Server --> MC[AWS Elemental MediaConnect]
    Server --> CW[Amazon CloudWatch]
    Server --> BR[Amazon Bedrock]

    Client --> Approval[Human tool permission]
    Approval --> Confirm[Exact flow ARN confirmation]
    Confirm --> Write[Start or stop adapter]
    Write --> Verify[Bounded state verification]
    Verify --> MC
```

The stdio entrypoint creates regional clients and registers typed tools.
Action-named adapters each talk to MediaConnect, CloudWatch, or Bedrock.
Workflows combine typed adapter results for issue detection, metric tables, and
thumbnail descriptions.

Read tools are always available. Write tools do not exist unless
`ALLOW_WRITES=true`; when enabled, the MCP client must obtain human permission,
the operator must repeat the exact flow ARN, and the adapter verifies the final
flow state.

## Prerequisites

For the fixture demo:

- Python 3.12 or newer. `uv` installs the repository's Python version from
  `.python-version`.
- [`uv`](https://docs.astral.sh/uv/).
- [`just`](https://just.systems/), installed with
  `uv tool install rust-just`.
- An MCP-compatible client, such as Amazon Q CLI, Claude Desktop, Cursor, or
  another client that can launch a stdio server.

For live AWS reads, also provide:

- AWS CLI v2 and configured AWS credentials.
- An AWS region containing at least one MediaConnect flow.
- IAM permission for `mediaconnect:ListFlows`, `mediaconnect:DescribeFlow`,
  `mediaconnect:DescribeFlowSourceMetadata`,
  `mediaconnect:DescribeFlowSourceThumbnail`, `cloudwatch:GetMetricData`, and
  `bedrock:InvokeModel`.
- Access to the model named by `THUMBNAIL_MODEL_ID` when using thumbnail
  analysis.

For optional writes, also provide `mediaconnect:StartFlow` and
`mediaconnect:StopFlow`. Existing MediaConnect flows and their data transfer
can incur AWS charges; this sample does not create those resources.

Check the local tools:

```bash
python3 --version
uv --version
just --version
```

Before live use, check the AWS identity and configured region:

```bash
aws sts get-caller-identity
aws configure get region
```

## Setup and Run

### Run Locally

1. Clone the repository and enter its root:

   ```bash
   git clone https://github.com/aws-samples/sample-agentic-video-operations.git
   cd sample-agentic-video-operations
   ```

2. Install `just`:

   ```bash
   uv tool install rust-just
   ```

3. Create the shared configuration:

   ```bash
   cp .env.example .env
   ```

4. Add the required runtime values to the root `.env`. Keep writes disabled:

   ```dotenv
   AWS_REGION=us-west-2
   THUMBNAIL_MODEL_ID=us.anthropic.claude-haiku-4-5-20251001-v1:0
   ALLOW_WRITES=false
   ```

5. Start the fixture-backed server:

   ```bash
   DEMO=1 DEMO_SCENARIO=srt_packet_loss just run mediaconnect
   ```

   Raw command:

   ```bash
   DEMO=1 DEMO_SCENARIO=srt_packet_loss ALLOW_WRITES=false uv run \
     --package mediaconnect-mcp-server \
     serve-mediaconnect
   ```

   A stdio MCP server waits silently for a client connection. Stop this smoke
   check with `Ctrl+C`; the client configuration in the next step launches the
   same server.

6. Add the live and demo entries from [`mcp.json`](mcp.json) to your MCP
   client. Replace the repository path with its absolute path:

   ```json
   {
     "mcpServers": {
       "mediaconnect": {
         "command": "uv",
         "args": [
           "run",
           "--directory",
           "/absolute/path/to/sample-agentic-video-operations",
           "--env-file",
           ".env",
           "--package",
           "mediaconnect-mcp-server",
           "serve-mediaconnect"
         ]
       },
       "mediaconnect-demo": {
         "command": "uv",
         "args": [
           "run",
           "--directory",
           "/absolute/path/to/sample-agentic-video-operations",
           "--package",
           "mediaconnect-mcp-server",
           "serve-mediaconnect"
         ],
         "env": {
           "DEMO": "1",
           "DEMO_SCENARIO": "srt_packet_loss",
           "ALLOW_WRITES": "false"
         }
       }
     }
   }
   ```

7. Restart the MCP client and send this known-good request:

   ```text
   Inspect source health for the demo MediaConnect flow. Is the source still
   connected, and what transport evidence explains downstream input loss?
   ```

   Expected result:

   ```text
   The assistant lists or describes demo-contribution, then reads source
   health metrics. It reports that the flow is ACTIVE and SourceConnected
   remains 1 while SourcePacketLossPercent rises from 0.1 to 9.7,
   SourceARQRecovered rises from 2 to 91, and unrecovered packets reach 44.
   The evidence points to upstream SRT packet loss rather than a stopped flow.
   ```

### Deploy to AWS

This standalone MCP sample has no deployment and `just deploy mediaconnect`
is intentionally unavailable. It runs locally against existing AWS
MediaConnect, CloudWatch, and Bedrock APIs.

The adapters are designed to be embedded later in an AgentCore-hosted media
operations hub as an in-process domain pack. That runtime has not landed, so it
is not documented here as an available deployment.

To use live AWS data today:

1. Set these values in the root `.env`:

   ```dotenv
   AWS_REGION=us-west-2
   THUMBNAIL_MODEL_ID=us.anthropic.claude-haiku-4-5-20251001-v1:0
   ALLOW_WRITES=false
   DEMO=false
   ```

2. Confirm that the active identity can see flows:

   ```bash
   export AWS_REGION=us-west-2
   aws mediaconnect list-flows \
     --region "$AWS_REGION" \
     --query "Flows[].{Name:Name,State:Status,Arn:FlowArn}"
   ```

3. Start the server:

   ```bash
   just run mediaconnect
   ```

   Raw command:

   ```bash
   uv run --env-file .env \
     --package mediaconnect-mcp-server \
     serve-mediaconnect
   ```

4. Use the `mediaconnect` live entry from the local MCP configuration.

Keep `ALLOW_WRITES=false` for diagnosis. To opt into start/stop tools, set it
to `true`, configure a private `APPROVAL_SIGNING_KEY`, and restart the server.
Every write still requires the MCP client's human permission prompt and an
exact `confirm_resource_id`.

### Verify the Deployment

There is no deployed runtime to verify yet. Verify the live local connection
through your MCP client with:

```text
List MediaConnect flows in the configured region and summarize their states.
For one ACTIVE flow, check source health over the last hour.
```

Expected result:

```text
The assistant calls list_flows, selects a returned ARN, and reports typed
source connection, loss, recovery, bitrate, and round-trip evidence. With
ALLOW_WRITES=false, start_flow and stop_flow are not available.
```

## Available Tools

| Tool | Read/write | What it does |
|---|---|---|
| `list_flows` | Read | Lists flows visible in the configured region |
| `describe_flow` | Read | Returns state, source, outputs, and AWS errors for one flow |
| `describe_flow_source_metadata` | Read | Returns transport-stream and NDI source metadata |
| `describe_flow_thumbnail` | Read | Describes the current source thumbnail with Bedrock |
| `get_flow_health_metrics` | Read | Reads flow transport and TR 101 290 metrics |
| `get_source_health_metrics` | Read | Reads source connection, packet loss, recovery, and merge metrics |
| `get_output_health_metrics` | Read | Reads output connection, packet, and payload metrics |
| `get_media_health_metrics` | Read | Reads source jitter, latency, uptime, and drop metrics |
| `get_content_quality_metrics` | Read | Reads missing-stream, black-frame, freeze, silence, and timecode metrics |
| `get_all_metrics` | Read | Reads all five metric categories |
| `check_flow_issues` | Read | Flags non-zero loss, drops, disconnects, errors, and missing streams |
| `get_metrics_table` | Read | Flattens metric points into chronological rows |
| `start_flow` | Write | Starts one approved flow and verifies `ACTIVE` |
| `stop_flow` | Write | Stops one approved flow and verifies `STANDBY` |

## Teardown

Stop the MCP process with `Ctrl+C`.

This sample creates no AWS infrastructure, so there is no
`just destroy mediaconnect` command. Do not delete MediaConnect flows merely
to clean up this local server; they are pre-existing operator-owned resources.

If you explicitly enabled writes and changed a flow state during testing,
restore the intended state through another separately approved `start_flow` or
`stop_flow` call. Remove the local `.env` when it is no longer needed because
it may contain the approval signing key.

When the AgentCore hub deployment lands, its README must own complete runtime,
log, image, memory, and role cleanup. Orphaned AWS resources can continue to
incur cost.

## Known Limitations

- This is an educational sample, not a production-ready operations service.
- The MCP server currently runs locally over stdio; an AgentCore hub deployment
  is approved but not implemented.
- The sample inspects existing MediaConnect resources and does not provision a
  test flow.
- IAM, tenant isolation, audit retention, rate limiting, retries, and
  high-availability behavior require production review.
- Issue detection uses explicit metric-name and threshold rules; it is not a
  complete transport fault classifier.
- Thumbnail descriptions are model-dependent and may vary.
- The `srt_packet_loss` fixture is one representative incident and does not
  reproduce every MediaConnect or CloudWatch behavior.
- Write tools are safe-by-default but still require organization-specific
  authorization, change-management, and rollback controls.
- Metric reads use a maximum seven-day window and five-minute periods.

## Development

Run the MediaConnect tests:

```bash
just test mediaconnect
```

Raw command:

```bash
uv run pytest samples/mediaconnect/tests
```

Run repository lint and formatting checks:

```bash
just lint
```

Raw commands:

```bash
uv run ruff check .
uv run ruff format --check .
```

Keep adapters importable as plain typed functions so the future in-process
domain pack can wrap them without importing MCP transport.

## Contributing

Read [`AGENTS.md`](../../AGENTS.md) and
[`CONTRIBUTING.md`](../../CONTRIBUTING.md) before opening a pull request.

## Security

Never commit credentials, `.env` files, approval keys, account IDs, ARNs, or
real flow identifiers. Keep writes disabled unless the operator intends to
change an exact flow, and review IAM permissions for least privilege. Report
security issues through the process in
[`CONTRIBUTING.md`](../../CONTRIBUTING.md#security-issue-notifications).

## License

This project is licensed under the MIT No Attribution License. See
[`LICENSE`](../../LICENSE).
