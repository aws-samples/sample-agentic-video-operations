# Hydrolix CDN Insights - Strands Agent

A CDN and streaming video data analyst assistant built with the **[Strands Agents SDK](https://strandsagents.com/)** and powered by **[Amazon Bedrock AgentCore](https://aws.amazon.com/bedrock/agentcore/)**.

## Overview

This agent provides an intelligent orchestrator specialized in Hydrolix CDN and streaming video analytics. It leverages Amazon Bedrock Claude models for natural language processing, Hydrolix for time-series data storage, and AgentCore Memory for conversation context management.

## Strands Agent Features

| Feature | Description |
|----------|----------|
| Model Provider | Amazon Bedrock (Claude Haiku 4.5) — Powers the orchestrator and all specialized subagents. |
| Specialized Subagents | The orchestrator routes user questions to domain-expert subagents, each with its own system prompt, tools, and specialized knowledge:<br><br>🔍 `hydrolix_agent` - **General Data Analyst** — Default subagent for time-series data exploration, traffic overviews, and ad-hoc queries across all dimensions.<br>🗄️ `cache_origin_agent` - **CDN Infrastructure Expert** — Specialized in cache hit/miss analysis, origin server latency, error rates, bandwidth cost, and edge location (POP) performance.<br>📺 `qoe_analysis_agent` - **Viewer Experience Expert** — Specialized in Quality of Experience (QoE) using CMCD player telemetry: buffer starvation, bitrate adaptation, throughput, startup performance, and geographic QoE breakdown.<br><br>💡 *New specialized subagents can be added — for example, an anti-piracy agent or a bot-detector agent.* |
| MCP Integration | **[Hydrolix MCP Server](https://github.com/hydrolix/mcp-hydrolix)** — Model Context Protocol package used by each specialized subagent to query the Hydrolix time-series database. Each subagent initializes its own MCP client to run queries independently. |
| Native Tools | Built-in Strands tools available to the orchestrator and each specialized subagent:<br>`current_time` - Provides current date and time information based on user's timezone.<br>`calculator` - Performs mathematical calculations: percentages, ratios, statistical metrics. |

## Project Structure

```
hydrolix-data-assistant-agentcore-strands/
├── app.py                              # Main application entry point
├── Dockerfile                          # Container configuration for AgentCore Runtime
├── orchestrator_instructions.txt       # Orchestrator system prompt and routing rules
├── requirements.txt                    # Python dependencies
├── src/
│   ├── tools/                          # Subagent implementations and instructions
│   │   ├── hydrolix_agent.py           # General data analyst subagent
│   │   ├── hydrolix_agent_instructions.txt
│   │   ├── cache_origin_agent.py       # CDN infrastructure expert subagent
│   │   ├── cache_origin_instructions.txt
│   │   ├── qoe_analysis_agent.py       # Viewer experience expert subagent
│   │   └── qoe_analysis_instructions.txt
│   ├── utils/                          # Utility functions and helpers
│   │   ├── stream_processor.py         # Shared stream processing for all subagents
│   │   ├── utils.py                    # DynamoDB query result storage
│   │   ├── request_context.py          # Request context singleton
│   │   └── MemoryHookProvider.py       # AgentCore Memory integration
│   └── mcp/                            # MCP Hydrolix server package
└── resources/                          # Additional resources
```

## Configuration

The agent uses the following environment variables:

| Variable | Description |
|----------|-------------|
| `MEMORY_ID` | AgentCore Memory ID for conversation context |
| `BEDROCK_MODEL_ID` | Bedrock model ID (default: `global.anthropic.claude-haiku-4-5-20251001-v1:0`) |
| `HYDROLIX_SECRET_ARN` | AWS Secrets Manager ARN for Hydrolix connection credentials |
| `HYDROLIX_TABLE` | Hydrolix table name (format: `database.table`, e.g., `ibc.demo`) |
| `QUESTION_ANSWERS_TABLE` | DynamoDB table name for storing query results |

## License

This project is licensed under the Apache-2.0 License.
