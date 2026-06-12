# Media Services LangChain — Multi-Agent System

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

> [!IMPORTANT]
> This sample is for **educational and reference purposes only**. It demonstrates multi-agent patterns with LangChain/LangGraph and Amazon Bedrock AgentCore. It is not intended for production use without security hardening, thorough testing, and customization for your environment.

A multi-agent system for live streaming operations using **LangChain/LangGraph** and **Amazon Bedrock AgentCore**. Three independently-deployed runtimes coordinate to manage MediaLive encoding and MediaConnect transport.

---

## Architecture

```
User → Coordinator Runtime (LangGraph ReAct)
         ├── invoke_eml ──→ EML Runtime (LangGraph + MediaLive tools)
         │
         └── invoke_emx ──→ EMX Runtime (LangGraph + MediaConnect tools)
```

| Runtime | Role | Tools |
|---------|------|-------|
| **Coordinator** | Classifies intent, plans tasks, routes to specialists, merges results | `invoke_eml`, `invoke_emx`, `write_todos` |
| **EML** | MediaLive specialist — encoding, channel management, monitoring | list/describe/start/stop channels, metrics, logs, schedule, issue detection |
| **EMX** | MediaConnect specialist — transport, flow management, routing | list/describe/start/stop flows, metrics, thumbnails, issue detection |

---

## Key Features

- **write_todos pattern** — Coordinator decomposes complex goals into structured, trackable tasks
- **LangGraph interrupt** — Destructive operations (start/stop/switch) pause for human approval
- **AgentCore Memory** — Single shared memory with `actor_id` namespace isolation per agent
- **Code Interpreter** — Lazy-initialized sandbox for data processing (scaffolded, Phase 2)
- **OpenTelemetry** — Full tracing with custom span names and attributes
- **Tool reuse** — EML/EMX wrap existing `medialive-mcp-server` and `mediaconnect-mcp-server` implementations (no domain logic duplication)

---

## Model Selection

The system uses `langchain.chat_models.init_chat_model` which supports multiple providers. Configure via environment variables:

| Provider | `AGENT_MODEL_ID` | `model_provider` | Notes |
|----------|-------------------|------------------|-------|
| **Bedrock cross-region** (default) | `us.anthropic.claude-sonnet-4-6` | `bedrock_converse` | Recommended. Auto-routes across regions for availability. |
| **Bedrock single-region** | `anthropic.claude-sonnet-4-6-20250514` | `bedrock_converse` | Pin to one region. Use when cross-region is unavailable. |
| **Anthropic direct** | `claude-sonnet-4-6-20250514` | `anthropic` | Requires `ANTHROPIC_API_KEY` env var. Bypasses Bedrock. |
| **OpenAI** | `gpt-4o` | `openai` | Requires `OPENAI_API_KEY` env var. |

### How to switch models

1. Set the environment variable before deploy:
   ```bash
   export AGENT_MODEL_ID="us.anthropic.claude-sonnet-4-6"
   ```

2. Or pass as a CDK parameter:
   ```bash
   cdk deploy --parameters BedrockModelId="us.anthropic.claude-sonnet-4-6"
   ```

3. For non-Bedrock providers, update `model_provider` in `shared/config.py` and add the provider's SDK to `requirements.txt`:
   ```bash
   # For Anthropic direct
   pip install langchain-anthropic
   
   # For OpenAI
   pip install langchain-openai
   ```

> [!NOTE]
> Non-Bedrock providers require API key environment variables set in the container. Add them to the CDK stack's `environmentVariables` configuration.

---

## Environment Setup

Copy the example env file and fill in your values:

```bash
cp .env.example .env
# Edit .env with your AWS account ID, region, and credentials profile
```

After `cdk deploy`, update the `.env` with the stack outputs (runtime ARNs, memory ID). The integration tests and CLI examples read from this file.

| Variable | Source |
|----------|--------|
| `AWS_ACCOUNT_ID` | Your AWS account |
| `COORDINATOR_ARN` | CDK output: `CoordinatorRuntimeArn` |
| `EML_RUNTIME_ARN` | CDK output: `EMLRuntimeArn` |
| `EMX_RUNTIME_ARN` | CDK output: `EMXRuntimeArn` |
| `BEDROCK_AGENTCORE_MEMORY_ID` | CDK output: `MemoryId` |

---

## Prerequisites

- Python 3.11+
- Node.js 18+ and npm (for CDK)
- Docker (for container builds — Colima or Docker Desktop)
- AWS credentials with Bedrock AgentCore permissions
- AWS CDK CLI (`npm install -g aws-cdk`)

---

## CDK Deployment

### Deploy

```bash
cd media-services-langchain/cdk
npm install
npx cdk deploy --parameters BedrockModelId="us.anthropic.claude-sonnet-4-6"
```

### Stack Outputs

After deployment, the stack outputs:

| Output | Description |
|--------|-------------|
| `CoordinatorRuntimeArn` | ARN to invoke the coordinator |
| `EMLRuntimeArn` | ARN to invoke EML directly |
| `EMXRuntimeArn` | ARN to invoke EMX directly |
| `CoordinatorEndpointName` | Endpoint name for the coordinator |
| `MemoryId` | Shared AgentCore memory resource ID |

### Validate Deployment

```bash
# Check stack outputs
aws cloudformation describe-stacks \
  --stack-name MediaServicesLangChainStack \
  --query 'Stacks[0].Outputs' --output table

# Test coordinator
aws bedrock-agentcore invoke-agent-runtime \
  --agent-runtime-arn "<CoordinatorRuntimeArn>" \
  --runtime-session-id "test-$(uuidgen)" \
  --payload "$(echo -n '{"prompt": "List all MediaLive channels"}' | base64)" \
  --region us-west-2 --cli-read-timeout 300 output.json

cat output.json
```

### Cleanup

```bash
npx cdk destroy
```

> [!NOTE]
> AgentCore runtimes incur costs while containers are running. Destroy the stack when not in use.

---

## Examples & Use Cases

### Simple query — single agent

```bash
export COORDINATOR_ARN="<your-coordinator-arn>"
export SESSION=$(uuidgen)

aws bedrock-agentcore invoke-agent-runtime \
  --agent-runtime-arn "$COORDINATOR_ARN" \
  --runtime-session-id "$SESSION" \
  --payload "$(echo -n '{"prompt": "List all MediaLive channels"}' | base64)" \
  --region us-west-2 --cli-read-timeout 300 output.json
```

**Result:** Coordinator routes to EML, returns channel list with IDs and states.

### Multi-agent pipeline health check

```bash
aws bedrock-agentcore invoke-agent-runtime \
  --agent-runtime-arn "$COORDINATOR_ARN" \
  --runtime-session-id "$SESSION" \
  --payload "$(echo -n '{"prompt": "Check the health of my full streaming pipeline — both the MediaConnect flow and the MediaLive channel"}' | base64)" \
  --region us-west-2 --cli-read-timeout 300 output.json
```

**Result:** Coordinator routes to BOTH EML and EMX, merges results into a unified pipeline status report with an end-to-end flow diagram.

### Destructive operation with approval

```bash
aws bedrock-agentcore invoke-agent-runtime \
  --agent-runtime-arn "$COORDINATOR_ARN" \
  --runtime-session-id "$SESSION" \
  --payload "$(echo -n '{"prompt": "Stop channel 5133350"}' | base64)" \
  --region us-west-2 --cli-read-timeout 300 output.json
```

**Result:** Coordinator identifies this as destructive, asks for confirmation before executing.

### Session memory

```bash
# Store context
aws bedrock-agentcore invoke-agent-runtime \
  --agent-runtime-arn "$COORDINATOR_ARN" \
  --runtime-session-id "$SESSION" \
  --payload "$(echo -n '{"prompt": "Remember: my escalation contact is ops-team@example.com"}' | base64)" \
  --region us-west-2 --cli-read-timeout 300 output.json

# Recall in same session
aws bedrock-agentcore invoke-agent-runtime \
  --agent-runtime-arn "$COORDINATOR_ARN" \
  --runtime-session-id "$SESSION" \
  --payload "$(echo -n '{"prompt": "What is my escalation contact?"}' | base64)" \
  --region us-west-2 --cli-read-timeout 300 output.json
```

**Result:** Agent recalls stored information within the same session via AgentCore Memory.

---

## Testing

### Unit Tests

```bash
cd media-services-langchain
python -m pytest tests/ -v
```

Tests validate graph routing logic with mocked state — no AWS calls required:

| Test File | What It Validates |
|-----------|-------------------|
| `test_coordinator_graph.py` | `classify_router` (fast_path vs planning), `approval_router` (approved/rejected), `merge_router` (pending vs complete) |
| `test_memory_isolation.py` | `actor_id` namespace isolation ensures agents don't cross-contaminate memory |

### Integration Tests

After deployment, run the examples above against the live stack. Verify:
1. EML agent returns channel data
2. EMX agent returns flow data
3. Coordinator routes to correct specialist(s)
4. Memory persists across turns in the same session

---

## Memory Model

All agents share one AgentCore Memory resource. Isolation via `actor_id`:

| Agent | actor_id | thread_id |
|-------|----------|-----------|
| Coordinator | `coordinator-{user_id}` | `session-{uuid}` |
| EML | `eml-{task_id}` | `task-{uuid}` |
| EMX | `emx-{task_id}` | `task-{uuid}` |

---

## IAM Separation

Each runtime has its own IAM role:
- **Coordinator** can only invoke EML/EMX runtimes (scoped to their ARNs)
- **EML** has MediaLive + CloudWatch permissions only
- **EMX** has MediaConnect + CloudWatch permissions only

---

## Observability

All runtimes emit OpenTelemetry traces:

| Span | Agent |
|------|-------|
| `coordinator.classify` | Coordinator |
| `coordinator.plan` | Coordinator |
| `coordinator.route` | Coordinator |
| `coordinator.respond` | Coordinator |
| `eml.execute` | EML |
| `emx.execute` | EMX |

---

## Related Samples

- [medialive-mcp-server](../medialive-mcp-server/) — Source of EML tool implementations
- [mediaconnect-mcp-server](../mediaconnect-mcp-server/) — Source of EMX tool implementations
- [hydrolix-cdn-insights](../hydrolix-cdn-insights/) — Reference CDK pattern (Strands Agents SDK version)

---

## License

Apache-2.0
