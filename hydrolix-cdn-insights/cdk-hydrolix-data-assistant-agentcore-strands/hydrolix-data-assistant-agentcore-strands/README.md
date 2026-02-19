# Hydrolix CDN Insights - Strands Agent

A CDN and streaming video data analyst assistant built with the **[Strands Agents SDK](https://strandsagents.com/)** and powered by **[Amazon Bedrock AgentCore](https://aws.amazon.com/bedrock/agentcore/)**.

## Overview

This agent provides an intelligent orchestrator specialized in Hydrolix CDN and streaming video analytics. It leverages Amazon Bedrock Claude models for natural language processing, Hydrolix for time-series data storage, and AgentCore Memory for conversation context management.

| Feature | Description |
|----------|----------|
| Model Provider | Amazon Bedrock (Claude Haiku 4.5) — Powers the orchestrator and all specialized subagents. |
| Specialized Subagents | The orchestrator routes user questions to domain-expert subagents, each with its own system prompt, tools, and specialized knowledge:<br><br>🔍 `hydrolix_agent` - **General Data Analyst** — Default subagent for time-series data exploration, traffic overviews, and ad-hoc queries across all dimensions.<br>🗄️ `cache_origin_agent` - **CDN Infrastructure Expert** — Specialized in cache hit/miss analysis, origin server latency, error rates, bandwidth cost, and edge location (POP) performance. Works with CDN access log data (near-100% fill rate).<br>📺 `qoe_analysis_agent` - **Viewer Experience Expert** — Specialized in Quality of Experience (QoE) using CMCD player telemetry: buffer starvation, bitrate adaptation, throughput, startup performance, and geographic QoE breakdown. Validates data quality before analysis.<br><br>💡 *New specialized subagents can be added to extend the system — for example, **an anti-piracy agent for detecting unauthorized content distribution, or a bot-detector agent for identifying suspicious traffic patterns**.* |
| MCP Integration | **[Hydrolix MCP Server](https://github.com/hydrolix/mcp-hydrolix)** — Model Context Protocol package used by each specialized subagent to query the Hydrolix time-series database, including schema inspection and SQL query execution. Each subagent initializes its own MCP client to run queries independently. |
| Native Tools | Built-in Strands tools available to the orchestrator and each specialized subagent:<br>`current_time` - Provides current date and time information based on user's timezone.<br>`calculator` - Performs mathematical calculations: percentages, ratios, statistical metrics. |

### User Interaction Workflow

1. The web application sends user questions about CDN performance or streaming metrics to the AgentCore Invoke
2. The Strands Agent (powered by Claude Haiku 4.5) processes natural language and routes to specialized subagents (`hydrolix_agent`, `qoe_analysis_agent`, or `cache_origin_agent`)
3. The specialized agents use MCP Hydrolix tools to execute SQL queries against the Hydrolix time-series database and formulate answers
4. AgentCore Memory captures session interactions and retrieves previous conversations for context
5. After the agent's response is received by the web application, the raw data query results are retrieved from the DynamoDB table to display both the answer and the corresponding records
6. For chart generation, the application invokes a model (powered by Claude Haiku 4.5) to analyze the agent's answer and raw data query results to generate the necessary data to render an appropriate chart visualization

### Example Insights & Actions

Beyond querying data, the agent system can be extended in two directions: enriching the conversational experience with automated actions, and triggering the agent directly from external events to investigate and act autonomously.

#### 💬 From Conversation — Actions triggered by agent insights during a user session

| Action | Example |
|--------|---------|
| 🔔 Alert & Notify | Detect cache hit rate drops below threshold and send alerts via Slack, PagerDuty, or Amazon SNS. |
| 📊 Report Generation | Generate periodic CDN performance reports and deliver them via email or push to an S3 bucket. |
| 🔧 CDN Configuration | Identify underperforming edge locations and trigger cache invalidation requests via CloudFront API. |
| 🎫 Ticketing Integration | When QoE degradation is detected, automatically create incidents in ServiceNow, Jira, or PagerDuty. |
| 🔗 Customer API Callback | Send analysis results to customer-facing APIs or webhooks for integration with their own platforms. |

#### ⚡ From External Triggers — Events that invoke the agent to investigate and take action

| Trigger | Example |
|---------|---------|
| 📺 **Media Workflow Triggers** | A CloudWatch Alarm or EventBridge rule detects a MediaLive channel failure or origin timeout — invokes the agent to diagnose root cause, check QoE impact, and trigger a MediaPackage origin failover or channel restart. |
| 🚨 CloudWatch Alarm | A cache hit rate alarm fires — the agent is invoked to investigate the drop, correlate with origin errors, and push updated cache rules or notify the on-call team. |
| 📡 Real-Time Monitoring | Grafana or CloudWatch detects anomalous traffic patterns — triggers the agent to analyze the spike, determine if it's organic or bot-driven, and push custom metrics or WAF rules. |
| 🛡️ Anti-Piracy Response | An EventBridge event flags suspicious download patterns — the agent investigates token usage, geo-distribution, and triggers token revocation or geo-blocking rules via CDN APIs. |
| 🤖 Bot Mitigation | A WAF rate-limit threshold is breached — the agent is invoked to analyze traffic signatures, confirm bot behavior, and push updated WAF rules to AWS WAF or third-party providers. |

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
