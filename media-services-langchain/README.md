# Media Services LangChain — Multi-Agent System

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

A multi-agent system for live streaming operations using **LangChain/LangGraph** and **Amazon Bedrock AgentCore**. Three independently-deployed runtimes coordinate to manage MediaLive encoding and MediaConnect transport.

## Architecture

```
User → Coordinator Runtime (LangGraph)
         ├─ classify → plan (write_todos) → approve → route → merge → respond
         │
         ├──[invoke_agent_runtime]──→ EML Runtime (LangGraph + MediaLive tools)
         │
         └──[invoke_agent_runtime]──→ EMX Runtime (LangGraph + MediaConnect tools)
```

| Runtime | Role | Tools |
|---------|------|-------|
| **Coordinator** | Classifies intent, plans tasks, routes to specialists, merges results | invoke_eml, invoke_emx |
| **EML** | MediaLive specialist | list/describe/start/stop channels, metrics, logs, schedule, issue detection |
| **EMX** | MediaConnect specialist | list/describe/start/stop flows, metrics, thumbnails, issue detection |

## Key Features

- **write_todos pattern** — Coordinator decomposes complex goals into structured, trackable tasks (LangChain deep agent equivalent)
- **LangGraph interrupt** — Destructive operations (start/stop/switch) pause for human approval
- **AgentCore Memory** — Single CfnMemory with actor_id namespace isolation per agent
- **Code Interpreter** — Lazy-initialized sandbox for data processing (Phase 2)
- **OpenTelemetry** — Full tracing with custom span names and attributes
- **Tool reuse** — EML/EMX wrap existing `medialive-mcp-server` and `mediaconnect-mcp-server` implementations

## Memory Model

All agents share one AgentCore Memory resource. Isolation via `actor_id`:

| Agent | actor_id | thread_id |
|-------|----------|-----------|
| Coordinator | `coordinator-{user_id}` | `session-{uuid}` |
| EML | `eml-{task_id}` | `task-{uuid}` |
| EMX | `emx-{task_id}` | `task-{uuid}` |

## Prerequisites

- Python 3.11+
- Node.js and npm (for CDK)
- Docker (for container builds)
- AWS credentials with AgentCore permissions

## Deploy

```bash
cd media-services-langchain/cdk
npm install
cdk deploy --parameters BedrockModelId="us.anthropic.claude-sonnet-4-6"
```

## Local Testing

```bash
# Run coordinator locally
cd media-services-langchain
pip install -r coordinator/requirements.txt
python -m coordinator.main
```

## Observability

All runtimes emit OpenTelemetry traces with these spans:

| Span | Agent |
|------|-------|
| `coordinator.classify` | Coordinator |
| `coordinator.plan` | Coordinator |
| `coordinator.route` | Coordinator |
| `coordinator.delegate` | Coordinator (per-task) |
| `eml.execute` | EML |
| `emx.execute` | EMX |
| `agent.memory.read` | All |
| `agent.memory.write` | All |

## IAM Separation

Each runtime has its own IAM role:
- **Coordinator** can only invoke EML/EMX runtimes (scoped to their ARNs)
- **EML** has MediaLive + CloudWatch permissions only
- **EMX** has MediaConnect + CloudWatch permissions only

## Related Samples

- [medialive-mcp-server](../medialive-mcp-server/) — Source of EML tool implementations
- [mediaconnect-mcp-server](../mediaconnect-mcp-server/) — Source of EMX tool implementations
- [hydrolix-cdn-insights](../hydrolix-cdn-insights/) — Reference CDK pattern (Strands version)

## License

Apache-2.0
