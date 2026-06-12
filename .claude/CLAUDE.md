# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A collection of AI agent samples for intelligent media operations — monitoring, diagnosing, and managing live streaming pipelines using MCP servers and Amazon Bedrock AgentCore. Each sample uses specialized agents (Strands Agents SDK or LangChain/LangGraph) to interact with AWS media services (MediaLive, MediaConnect), CDN analytics (Hydrolix, CMCD/InfluxDB), and observability data.

## Repository Structure

| Directory | What It Is | Agent Framework | Entry Points |
|-----------|-----------|-----------------|--------------|
| `medialive-mcp-server/` | MediaLive channel management + monitoring | Strands Agent + FastMCP | `server.py` (MCP stdio), `main.py` (AgentCore) |
| `mediaconnect-mcp-server/` | MediaConnect flow management + monitoring | FastMCP only | `server.py` (MCP stdio) |
| `cmcd-mcp-server/` | CMCD streaming QoE analytics via InfluxDB | FastMCP only | `cmcd_server.py` (MCP stdio) |
| `hydrolix-cdn-insights/` | Multi-agent CDN analytics (orchestrator + 3 subagents) | Strands Agent + AgentCore | `app.py` (AgentCore), CDK + Amplify |
| `media-services-langchain/` | Multi-agent streaming ops (Coordinator + EML + EMX) | LangChain/LangGraph + AgentCore | `coordinator/main.py`, `eml/main.py`, `emx/main.py` |

`mcp-eml-reference/` is gitignored — superseded by `medialive-mcp-server/`.

## Architecture Patterns

### Dual Entry Point Pattern (medialive-mcp-server)

- `server.py` (FastMCP): Registers individual tools, spawned by local MCP clients via stdio
- `main.py` → `src/app.py` (Strands Agent): Uses composite tools pattern (15 tools → 6 composites for ~67% schema token reduction), deployed to AgentCore

### AgentCore Runtime Pattern

```python
from bedrock_agentcore.runtime import BedrockAgentCoreApp
app = BedrockAgentCoreApp()

@app.entrypoint
async def invoke(payload, context):
    # actor_id from X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actor-Id header
    # session_id from context.session_id
    # Container is session-pinned — global agent survives across invocations
```

### Multi-Agent Orchestration (hydrolix-cdn-insights)

Orchestrator routes to specialized subagents (`hydrolix_agent`, `qoe_analysis_agent`, `cache_origin_agent`). Each subagent gets its own system prompt, tools, and MCP client. Subagents are stateless — spawned per-invocation with `callback_handler=None`.

### LangChain/LangGraph Multi-Agent (media-services-langchain)

Three AgentCore runtimes using `langgraph.prebuilt.create_react_agent`:
- **Coordinator** (`coordinator/main.py`): ReAct agent with `invoke_eml`, `invoke_emx`, `write_todos` tools. Routes to specialists via `AgentCoreRuntimeClient`.
- **EML** (`eml/main.py`): ReAct agent wrapping `medialive-mcp-server/src/tools/` as LangChain `@tool` decorators.
- **EMX** (`emx/main.py`): ReAct agent wrapping `mediaconnect-mcp-server/tools/` as LangChain `@tool` decorators.

Key patterns:
- `shared/state.py`: `CoordinatorState(MessagesState)` with custom `merge_todos` reducer
- `shared/runtime_client.py`: boto3 `invoke_agent_runtime` wrapper for inter-agent calls
- `shared/memory.py`: `AgentCoreMemorySaver` factory with namespace isolation via `actor_id`
- Module-level singletons: graph/client/checkpointer created once (containers are session-pinned)
- `.env` file holds runtime ARNs and config; `.env.example` is the template

### Composite Tool Pattern

Group related operations into one tool with an `action` parameter and internal dispatch table:
```python
@tool
def channel_management(action: str, channel_id: str = None) -> str:
    dispatch = {"list": ..., "describe": ..., "start": ..., "stop": ..., "thumbnail": ...}
```
Also maintain `TOOL_DISPATCH_MAP` for backward-compatible code_mode command names.

### Memory Integration

Two approaches in use:
1. **AgentCoreMemorySessionManager** (global singleton agent): Simpler, but accumulates stale tool results across requests. Used in `medialive-mcp-server/main.py`.
2. **MemoryHookProvider** (per-request agent): Avoids stale state by creating fresh agent per invocation. Recommended for production. Used in `hydrolix-cdn-insights/`.

Memory creation uses `semanticMemoryStrategy` with configurable `eventExpiryDuration` (7-30 days).

### Code Interpreter

Available as `code_mode` tool — sends data + Python script to sandboxed runtime. Skip sandbox for responses < 4KB (use local exec). Session pooling (`max_size=2`, `ttl_seconds=300`) eliminates cold starts.

## Commands

### Local MCP Server Development

```bash
cd medialive-mcp-server   # or mediaconnect-mcp-server, cmcd-mcp-server
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python3 server.py          # starts MCP server via stdio
```

### AgentCore Deployment

```bash
cd medialive-mcp-server
export AWS_REGION=us-west-2
export AGENT_MODEL_ID=us.anthropic.claude-sonnet-4-6
uv run agentcore launch --auto-update-on-conflict
```

### CDK Deployment (hydrolix-cdn-insights)

```bash
cd hydrolix-cdn-insights/cdk-hydrolix-data-assistant-agentcore-strands
npm install
cdk deploy --parameters BedrockModelId="global.anthropic.claude-haiku-4-5-20251001-v1:0" --parameters HydrolixTable="your_database.your_table"
```

### CDK Deployment (media-services-langchain)

```bash
cd media-services-langchain/cdk
npm install
npx cdk deploy --parameters BedrockModelId="us.anthropic.claude-sonnet-4-6"
# After deploy, update .env with stack outputs (runtime ARNs, memory ID)
```

### Integration Tests (media-services-langchain)

```bash
cd media-services-langchain
python3 -m venv .venv && source .venv/bin/activate
pip install -r tests/requirements.txt
# Requires .env with valid runtime ARNs + AWS credentials
python -m pytest tests/test_integration.py -v --timeout=300
```

### Running Tests

```bash
# Integration tests (require running agent + AWS credentials)
cd medialive-mcp-server/tests && python3 -m pytest -v

# Unit tests (mocked, no network)
cd <agent>/tests/unit && python3 -m pytest -v --tb=short
```

### Local Agent Testing

```bash
cd hydrolix-cdn-insights/cdk-hydrolix-data-assistant-agentcore-strands/hydrolix-data-assistant-agentcore-strands
python3 app.py  # starts on port 8080

# In another terminal:
export SESSION_ID=$(uuidgen)
curl -X POST http://localhost:8080/invocations -H "Content-Type: application/json" \
  -d '{"prompt": "Hello!", "session_id": "'$SESSION_ID'", "last_k_turns": 20}'
```

## Key Configuration

### Environment Variables

| Variable | Default | Used By |
|----------|---------|---------|
| `AGENT_MODEL_ID` | `us.anthropic.claude-sonnet-4-6` | All agents (Strands + LangChain) |
| `THUMBNAIL_MODEL_ID` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Vision analysis |
| `BEDROCK_AGENTCORE_MEMORY_ID` | _(none)_ | Memory-enabled agents |
| `AWS_REGION` | `us-west-2` | All AWS calls |
| `MEDIALIVE_DEFAULT_CHANNEL_ID` | _(none)_ | MediaLive tools |
| `EML_RUNTIME_ARN` | _(none)_ | LangChain coordinator → EML |
| `EMX_RUNTIME_ARN` | _(none)_ | LangChain coordinator → EMX |

For `media-services-langchain/`, all configuration is in `.env` (copied from `.env.example`). The `.env` file is gitignored.

### .bedrock_agentcore.yaml

Runtime configuration for AgentCore deploy. Key settings: `platform: linux/arm64`, `container_runtime: none`, `network_mode: PUBLIC`, `server_protocol: HTTP`, `observability: enabled: true`.

## Security Rules

- Never create Lambda Function URLs — all Lambda behind API Gateway with auth
- Never use `Principal: *` or `AuthType: NONE`
- Never hardcode credentials — use env vars or Secrets Manager
- All S3 buckets must have BlockPublicAccess and SSE enabled
- IAM policies must scope `Resource` to specific ARNs (wildcards only when API requires it like `cloudwatch:PutMetricData`)
- Destructive operations (start/stop/input switch/route changes) require explicit user permission; read-only operations are always safe

## Agent System Prompt Rules

- ALWAYS instruct agents to call direct tools first — never "prefer code_mode"
- Explicitly list which tool handles which action in the system prompt
- Keep prompts short: behavioral rules only, no capability duplication with `@tool` docstrings
- Agent behavioral instructions live in `prompts/agent_instructions.md` (loaded at startup, edit without touching Python)

## Model Selection

| Role | Model | Rationale |
|------|-------|-----------|
| Main agent | `us.anthropic.claude-sonnet-4-6` | Tool selection + multi-step reasoning |
| Dispatch/vision | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Fast classification, lightweight |

Use cross-region inference profiles (`us.*`) for availability. Never use Haiku as a main agent — it misroutes tool calls.

## Authorization Pattern

All samples use IAM role-based auth with `bedrock-agentcore.amazonaws.com` as service principal. No OAuth or custom authorizers at the backend. Front-end (Amplify) uses Amazon Cognito for user authentication. Hydrolix credentials stored in Secrets Manager.

## Pre-Publish Checklist

Before committing to public repo: scan for AWS account IDs in ARN contexts, access keys (AKIA/ASIA), hardcoded passwords/tokens, internal hostnames, and resource-specific IDs (channel IDs, memory IDs, agent ARNs). All configurable values must come from env vars or CfnParameters.
