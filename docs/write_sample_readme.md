# Write a Sample README

Use this template for every runnable sample. Keep the README on the shortest
path from clone to a verified result. Move deeper material into focused files
under `docs/`.

The example below uses the `mediaconnect` MCP sample. Replace its names,
commands, tools, and cleanup steps with those of the sample being documented.

---

# MediaConnect MCP Server

Inspect MediaConnect flow health, metrics, and output thumbnails from an
MCP-compatible assistant.

> [!IMPORTANT]
> This sample is for educational and reference purposes. It is not
> production-ready without security hardening, testing, and customization.

## Purpose

Use this sample when an operator needs to understand whether live-video
transport is healthy before investigating downstream encoding or delivery.

The first successful run starts the MCP server locally and makes its read-only
flow inspection tools available to an MCP client.

## Architecture

```mermaid
flowchart LR
    Operator --> Client[MCP client]
    Client --> Server[MediaConnect MCP server]
    Server --> MC[AWS Elemental MediaConnect]
    Server --> CW[Amazon CloudWatch]
    Server --> BR[Amazon Bedrock thumbnail analysis]
```

The entrypoint handles MCP transport. Focused adapters call MediaConnect,
CloudWatch, or Bedrock. Write adapters are unavailable unless
`ALLOW_WRITES=true`, and every write requires approval and verification.

## Prerequisites

- Python 3.12 or newer (`uv` installs it automatically from `.python-version`).
- [`uv`](https://docs.astral.sh/uv/).
- [`just`](https://just.systems/), installed with `uv tool install rust-just`.
- An MCP-compatible client.
- For AWS-backed use: configured AWS credentials and access to the services
  shown in the architecture diagram.

Check the complete repository prerequisites:

```bash
just doctor
```

Raw command:

```bash
uv run scripts/check_prerequisites.py
```

## Setup and Run

### Run Locally

1. Clone the repository and enter it:

   ```bash
   git clone https://github.com/aws-samples/sample-agentic-video-operations.git
   cd sample-agentic-video-operations
   ```

2. Install `just`:

   ```bash
   uv tool install rust-just
   ```

3. Create the root configuration, then add the variables listed in this
   sample's `.env.example`:

   ```bash
   cp .env.example .env
   ```

4. Start the sample:

   ```bash
   just run mediaconnect
   ```

   Raw command:

   ```bash
   uv run --package mediaconnect-mcp-server serve-mediaconnect
   ```

5. Configure an MCP client:

   ```json
   {
     "mcpServers": {
       "mediaconnect": {
         "command": "uv",
         "args": [
           "run",
           "--directory",
           "/path/to/sample-agentic-video-operations",
           "--package",
           "mediaconnect-mcp-server",
           "serve-mediaconnect"
         ]
       }
     }
   }
   ```

6. Send a known-good request:

   ```text
   List my MediaConnect flows and summarize their current state.
   ```

   Expected result:

   ```text
   The assistant calls the read-only flow listing tool and returns each
   available flow with its name and current state.
   ```

### Deploy to AWS

This sample has no standalone deployment. It runs in AWS as the MediaConnect
specialist in the `langchain` sample:

```bash
just deploy langchain
```

Raw command:

```bash
cd samples/hub/cdk
npx cdk deploy \
  --parameters BedrockModelId="$AGENT_MODEL_ID"
```

> [!WARNING]
> Deployment creates billable AWS resources. Confirm the account and region
> printed by the command before continuing.

### Verify the Deployment

Invoke the deployed coordinator with a known-good request:

```bash
export COORDINATOR_ARN="<CoordinatorRuntimeArn>"
export SESSION_ID="$(uuidgen)"
aws bedrock-agentcore invoke-agent-runtime \
  --agent-runtime-arn "$COORDINATOR_ARN" \
  --runtime-session-id "$SESSION_ID" \
  --payload "$(printf '%s' '{"prompt":"List all MediaConnect flows"}' | base64)" \
  --region "$AWS_REGION" \
  --cli-read-timeout 300 \
  output.json
```

Expected result:

```text
The coordinator routes the request to the MediaConnect specialist and returns
the available flows with their names and current states.
```

## Available Tools

| Tool | Read/write | What it does |
|---|---|---|
| `list_flows` | Read | Lists MediaConnect flows and their states |
| `describe_flow` | Read | Returns configuration and health for one flow |
| `describe_flow_thumbnail` | Read | Analyzes a flow output thumbnail |
| `stop_flow` | Write | Stops one approved flow and verifies its state |

## Teardown

Stop the local MCP process with `Ctrl+C`.

Destroy the AWS deployment:

```bash
just destroy langchain
```

Raw command:

```bash
cd samples/hub/cdk
npx cdk destroy
```

Teardown checklist:

- [ ] Stop local processes.
- [ ] Run `just destroy <key>` for every deployed sample.
- [ ] Run `just demo-channel delete` if a demo channel was created.
- [ ] Confirm the CloudFormation stacks are deleted.
- [ ] Remove manually created media resources.
- [ ] Check for retained log groups, container images, secrets, or data.

Orphaned infrastructure can continue to incur cost.

## Known Limitations

- The sample is educational and is not production-ready.
- Model responses are nondeterministic.
- IAM, tenant isolation, retries, and scaling require production review.
- Write operations require `ALLOW_WRITES=true` and additional safeguards.
- Demo fixtures do not reproduce every AWS service behavior.

## Development

Run the offline checks:

```bash
just test mediaconnect
just lint
```

Keep adapters focused on one external action, return typed results, and use
fixture-backed tests.

## Contributing

Read the root [`AGENTS.md`](../AGENTS.md) and
[`CONTRIBUTING.md`](../CONTRIBUTING.md) before opening a pull request.

## Security

Never commit credentials, `.env` files, account IDs, ARNs, or real media
resource IDs. Report security issues through the process in
[`CONTRIBUTING.md`](../CONTRIBUTING.md#security-issue-notifications).

## License

This project is licensed under the MIT No Attribution License. See
[`LICENSE`](../LICENSE).
