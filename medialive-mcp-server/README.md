# MediaLive MCP Server

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

A hybrid Model Context Protocol (MCP) server for managing and monitoring AWS Elemental MediaLive channels. Provides AI-powered tools for live video encoding operations including channel management, schedule management, 5-category CloudWatch monitoring, thumbnail analysis via Amazon Bedrock, and a sandboxed code interpreter for data processing.

## What is AWS Elemental MediaLive?

[AWS Elemental MediaLive](https://aws.amazon.com/medialive/) is a real-time video encoding service that creates high-quality live video streams for delivery to broadcast televisions and internet-connected devices. It encodes live video from a variety of sources, including on-premises encoders, AWS Elemental MediaConnect, and Amazon S3, and outputs to MediaPackage, MediaStore, or directly to HTTP/RTMP destinations.

## Architecture

This project has two entry points sharing the same tool core:

- `server.py` (FastMCP) — spawned by local MCP clients via stdio, registers each tool individually
- `main.py` → `app.py` (Strands Agent) — spawned by AgentCore runtime, uses composite tools pattern for token reduction, includes FastAPI endpoints for UI

```
                    ┌──────────────────────────────────────────────┐
                    │         medialive-mcp-server/                │
                    │                                              │
┌──────────┐       │  ┌─────────────┐     ┌──────────────────┐   │    ┌─────────────────┐
│ MCP      │──────▶│  │ server.py   │────▶│ src/tools/       │   │───▶│ AWS APIs         │
│ Client   │       │  │ (FastMCP)   │     │  medialive_tools │   │    │ ├─ MediaLive     │
└──────────┘       │  └─────────────┘     │  schedule_tools  │   │    │ ├─ CloudWatch    │
                    │        │             │  thumbnails      │   │    │ ├─ CloudWatch    │
                    │        │             │  truncation      │   │    │ │   Logs         │
                    │        ▼             │  constants       │   │    │ └─ Bedrock       │
                    │  ┌─────────────┐     └──────────────────┘   │    └─────────────────┘
                    │  │ src/        │              ▲              │
                    │  │ monitoring/ │              │              │
                    │  │ (5-category │──────────────┘              │
                    │  │  CloudWatch)│              │              │
                    │  └─────────────┘              │              │
                    │        ▲                      │              │
┌──────────┐       │  ┌─────┴───────┐     ┌────────┴─────────┐   │
│ AgentCore│──────▶│  │ main.py     │────▶│ src/app.py       │   │
│ / UI     │       │  │ (AgentCore) │     │ (Strands Agent + │   │
└──────────┘       │  └─────────────┘     │  FastAPI + 6     │   │
                    │                      │  composite tools) │   │
                    │                      └──────────────────┘   │
                    └──────────────────────────────────────────────┘
```

## Features

### Channel Management
- **List Channels** — Enumerate all MediaLive channels with IDs, ARNs, and state
- **Describe Channel** — Get detailed configuration, input attachments, and pipeline status
- **Start/Stop Channel** — Control channel lifecycle
- **Thumbnail Analysis** — AI-powered visual analysis of channel thumbnails using Claude via Amazon Bedrock

### Schedule Management
- **Describe Schedule** — List all schedule actions for a channel
- **Input Switch** — Schedule timed or immediate input switches
- **SCTE-35** — Schedule splice insert actions for ad signaling
- **Pause/Unpause** — Schedule pipeline pause and unpause actions
- **Delete Action** — Remove schedule actions

### CloudWatch Monitoring (5 Categories)
- **Channel Health** — Active alerts, pipeline lock, fill milliseconds, frame rate, dropped frames
- **Input Health** — Network bitrate, input loss, RTP packets, FEC recovery, input errors
- **Output Health** — Network out, active outputs, HTTP 4xx/5xx errors, audio levels, dropped frames
- **Media Health** — Timecodes, audio levels, input error seconds, fill milliseconds
- **Content Quality** — MQCS score, black frame detection, freeze frame detection, continuity errors

### Issue Detection
- **Cross-Category Issue Scan** — Scan all monitoring categories for problems with HIGH/MEDIUM severity classification
- **Metrics Table** — Export key metrics in tabular format for charting and visualization

## Prerequisites

- Python 3.11+
- AWS credentials configured (`aws configure`)
- AWS region set in your AWS config
- Required IAM permissions (see [Required Permissions](#required-permissions))
- Amazon Bedrock access (for thumbnail analysis with Claude)

## Environment Variables

All configuration is via environment variables — no hardcoded account or channel IDs.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AWS_REGION` | No | `us-west-2` | AWS region for all API calls |
| `MEDIALIVE_DEFAULT_CHANNEL_ID` | No | _(none)_ | Default channel ID when not passed explicitly |
| `THUMBNAIL_MODEL_ID` | No | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Bedrock model for thumbnail analysis |
| `AGENT_MODEL_ID` | No | `us.anthropic.claude-sonnet-4-6` | Bedrock model for the Strands Agent |
| `BEDROCK_AGENTCORE_MEMORY_ID` | No | _(none)_ | AgentCore Memory ID (for Strands Agent deployment) |
| `MEDIALIVE_TEST_CHANNEL_ID` | No | _(none)_ | Channel ID for running integration tests |
| `FASTMCP_LOG_LEVEL` | No | `INFO` | Log level for the FastMCP server |

## Setup

### 1. Set Up Virtual Environment

```bash
cd sample-agentic-video-operations/medialive-mcp-server

python3 -m venv venv
source venv/bin/activate  # macOS/Linux
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Verify the MCP Configuration File

The `mcp.json` file configures local MCP clients to spawn `server.py`:

```json
{
  "mcpServers": {
    "medialive-mcp": {
      "command": "python3",
      "args": ["server.py"],
      "cwd": "<DIRECTORY_PATH>",
      "env": {
        "AWS_REGION": "us-west-2",
        "MEDIALIVE_DEFAULT_CHANNEL_ID": "<YOUR_CHANNEL_ID>",
        "THUMBNAIL_MODEL_ID": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "FASTMCP_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

Replace `<DIRECTORY_PATH>` with the absolute path to the `medialive-mcp-server/` directory and `<YOUR_CHANNEL_ID>` with your MediaLive channel ID.

## Integration with Kiro

Add the MCP server configuration to your Kiro workspace:

1. Open the MCP configuration file at `.kiro/settings/mcp.json`
2. Add the MediaLive MCP server entry:

```json
{
  "mcpServers": {
    "medialive-mcp": {
      "command": "python3",
      "args": ["server.py"],
      "cwd": "/path/to/sample-agentic-video-operations/medialive-mcp-server",
      "env": {
        "AWS_REGION": "us-west-2",
        "MEDIALIVE_DEFAULT_CHANNEL_ID": "<YOUR_CHANNEL_ID>",
        "THUMBNAIL_MODEL_ID": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "FASTMCP_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

## Integration with Amazon Q CLI

### 1. Copy the mcp.json File to Q CLI Directory

```bash
cp mcp.json ~/.aws/amazonq/mcp.json
```

Edit the file to set your `cwd`, `AWS_REGION`, and `MEDIALIVE_DEFAULT_CHANNEL_ID`.

### 2. Running Amazon Q CLI

```bash
q chat
```

## Integration with Claude Code

Add the MCP server to your Claude Code project configuration:

```bash
claude mcp add medialive-mcp -- python3 /path/to/sample-agentic-video-operations/medialive-mcp-server/server.py
```

Or add it manually to `.claude/settings.json`:

```json
{
  "mcpServers": {
    "medialive-mcp": {
      "command": "python3",
      "args": ["/path/to/sample-agentic-video-operations/medialive-mcp-server/server.py"],
      "env": {
        "FASTMCP_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

## Available Tools

### Channel Management

| Tool | Description | Parameters |
|------|-------------|------------|
| `mcp_list_channels` | List all MediaLive channels with IDs, ARNs, and state | None |
| `mcp_describe_channel` | Get detailed channel configuration and pipeline status | `channel_id` (optional) |
| `mcp_start_channel` | Start a MediaLive channel | `channel_id` (optional) |
| `mcp_stop_channel` | Stop a running MediaLive channel | `channel_id` (optional) |
| `mcp_describe_channel_thumbnail` | AI-powered visual analysis of channel thumbnail via Bedrock | `channel_id` (optional), `pipeline_id` (default: "0") |

### Channel Monitoring

| Tool | Description | Parameters |
|------|-------------|------------|
| `mcp_get_channel_metrics` | Get basic CloudWatch metrics (frame rate, network, fill, alerts) | `channel_id` (optional), `hours_back` (default: 1) |
| `mcp_get_channel_logs` | Get recent CloudWatch log events | `channel_id` (optional), `hours_back` (default: 1) |

### Schedule Management

| Tool | Description | Parameters |
|------|-------------|------------|
| `mcp_describe_schedule` | List all schedule actions for a channel | `channel_id` (optional) |
| `mcp_create_input_switch_action` | Schedule a timed input switch | `channel_id`, `action_name`, `input_attachment_name`, `start_time` |
| `mcp_create_immediate_input_switch` | Immediately switch the active input | `channel_id`, `action_name`, `input_attachment_name` |
| `mcp_create_scte35_action` | Schedule a SCTE-35 splice insert for ad signaling | `channel_id`, `action_name`, `start_time`, `splice_event_id`, `duration` (optional) |
| `mcp_create_pause_action` | Schedule a pipeline pause | `channel_id`, `action_name`, `start_time`, `pipeline_id` (default: "PIPELINE_0") |
| `mcp_create_unpause_action` | Schedule a pipeline unpause | `channel_id`, `action_name`, `start_time`, `pipeline_id` (default: "PIPELINE_0") |
| `mcp_delete_schedule_action` | Delete a schedule action | `channel_id`, `action_name` |

### CloudWatch Monitoring (5-Category)

| Tool | Description | Parameters |
|------|-------------|------------|
| `mcp_get_all_metrics` | Get all metrics across all 5 categories | `channel_id` (required), `hours_back` (default: 1) |
| `mcp_get_channel_health_metrics` | Channel health: alerts, pipeline lock, fill, frame rate, drops | `channel_id` (required), `hours_back` (default: 1) |
| `mcp_get_input_health_metrics` | Input health: network in, input loss, RTP packets, FEC recovery | `channel_id` (required), `hours_back` (default: 1) |
| `mcp_get_output_health_metrics` | Output health: network out, active outputs, HTTP errors, audio | `channel_id` (required), `hours_back` (default: 1) |
| `mcp_get_media_health_metrics` | Media health: timecodes, audio levels, input errors, fill | `channel_id` (required), `hours_back` (default: 1) |
| `mcp_get_content_quality_metrics` | Content quality: MQCS, black/freeze frames, continuity errors | `channel_id` (required), `hours_back` (default: 1) |

### Issue Detection & Analysis

| Tool | Description | Parameters |
|------|-------------|------------|
| `mcp_check_channel_issues` | Cross-category issue scan with severity classification | `channel_id` (required), `hours_back` (default: 24) |
| `mcp_get_metrics_table` | Metrics in tabular format for graphing | `channel_id` (required), `hours_back` (default: 6) |

## Sample Questions

### Channel Management & Status
- "List all my MediaLive channels"
- "Describe channel 1234567"
- "Start the production channel"
- "What does the thumbnail look like for channel 1234567?"

### Schedule Operations
- "Show me the schedule for channel 1234567"
- "Create an input switch to backup-input at 2025-01-15T10:00:00Z"
- "Immediately switch to the slate input"
- "Schedule a SCTE-35 ad break at the top of the hour"
- "Pause pipeline 0 for maintenance"

### Health Monitoring
- "Get all metrics for channel 1234567 from the past hour"
- "Check channel health metrics for dropped frames"
- "Get input health — any packet loss or input errors?"
- "Check output health for HTTP errors"
- "Get content quality metrics — any black frames or frozen video?"
- "What's the media health status?"

### Issue Detection & Troubleshooting
- "Check for issues on channel 1234567 in the past 24 hours"
- "Are there any problems across all categories?"
- "Get metrics in table format for graphing"

## CloudWatch Metrics Reference

### Channel Health Metrics

| Metric | Description | Unit | Dimensions |
|--------|-------------|------|------------|
| `ActiveAlerts` | Number of active alerts on the channel | Count | ChannelId, Pipeline |
| `PipelinesLocked` | Whether pipelines are locked (1=locked, 0=unlocked) | Count | ChannelId, Pipeline |
| `InputVideoAligned` | Whether input video is aligned across pipelines | Count | ChannelId, Pipeline |
| `FillMsec` | Milliseconds of fill content (no source content available) | Milliseconds | ChannelId, Pipeline |
| `InputVideoFrameRate` | Input video frame rate | Count | ChannelId, Pipeline |
| `DroppedFrames` | Number of dropped frames | Count | Pipeline, Region |
| `SvqTime` | Time spent in SVQ (encoder quality adjustment) | Milliseconds | Pipeline, Region |

### Input Health Metrics

| Metric | Description | Unit | Dimensions |
|--------|-------------|------|------------|
| `NetworkIn` | Inbound network bitrate | Megabits/Second | ChannelId, Pipeline |
| `InputLossSeconds` | Seconds of input signal loss | Seconds | ChannelId, Pipeline |
| `InputVideoFrameRate` | Input video frame rate | Count | ChannelId, Pipeline |
| `RtpPacketsReceived` | Total RTP packets received | Count | ChannelId, Pipeline |
| `RtpPacketsLost` | RTP packets lost during transit | Count | ChannelId, Pipeline |
| `RtpPacketsRecoveredViaFec` | RTP packets recovered via FEC | Count | ChannelId, Pipeline |
| `FecRowPacketsReceived` | FEC row packets received | Count | ChannelId, Pipeline |
| `FecColumnPacketsReceived` | FEC column packets received | Count | ChannelId, Pipeline |
| `ChannelInputErrorSeconds` | Seconds with input errors | Seconds | ChannelId, Pipeline |
| `PrimaryInputActive` | Whether the primary input is active (1=active) | Count | ChannelId, Pipeline |

### Output Health Metrics

| Metric | Description | Unit | Dimensions |
|--------|-------------|------|------------|
| `NetworkOut` | Outbound network bitrate | Megabits/Second | ChannelId, Pipeline |
| `ActiveOutputs` | Number of active outputs | Count | OutputGroupName, ChannelId, Pipeline |
| `Output4xxErrors` | HTTP 4xx errors on outputs | Count | OutputGroupName, ChannelId, Pipeline |
| `Output5xxErrors` | HTTP 5xx errors on outputs | Count | OutputGroupName, ChannelId, Pipeline |
| `OutputAudioLevelDbfs` | Output audio level in dBFS | Count | AudioDescriptionName, ChannelId, Pipeline |
| `OutputAudioLevelLkfs` | Output audio level in LKFS | Count | AudioDescriptionName, ChannelId, Pipeline |
| `ComplexFrcPresent` | Whether complex frame rate conversion is active | Count | ChannelId, Pipeline |
| `DroppedFrames` | Number of dropped frames | Count | Pipeline, Region |
| `SvqTime` | Time spent in SVQ | Milliseconds | Pipeline, Region |

### Media Health Metrics

| Metric | Description | Unit | Dimensions |
|--------|-------------|------|------------|
| `InputTimecodesPresent` | Whether input timecodes are present | Count | ChannelId, Pipeline |
| `OutputAudioLevelDbfs` | Output audio level in dBFS | Count | AudioDescriptionName, ChannelId, Pipeline |
| `OutputAudioLevelLkfs` | Output audio level in LKFS | Count | AudioDescriptionName, ChannelId, Pipeline |
| `ChannelInputErrorSeconds` | Seconds with input errors | Seconds | ChannelId, Pipeline |
| `FillMsec` | Milliseconds of fill content | Milliseconds | ChannelId, Pipeline |

### Content Quality Metrics

| Metric | Description | Unit | Dimensions |
|--------|-------------|------|------------|
| `MinMQCS` | Minimum Media Quality Confidence Score | Count | OutputGroupName, ChannelId, Pipeline |
| `MqcsBlackFrameDetected` | Black frame detection flag | Count | ChannelId, Pipeline |
| `MqcsFreezeFrameDetected` | Freeze frame detection flag | Count | ChannelId, Pipeline |
| `MqcsContinuityCounterErrors` | Transport stream continuity counter errors | Count | ChannelId, Pipeline |
| `FillMsec` | Milliseconds of fill content | Milliseconds | ChannelId, Pipeline |
| `InputLossSeconds` | Seconds of input signal loss | Seconds | ChannelId, Pipeline |
| `DroppedFrames` | Number of dropped frames | Count | Pipeline, Region |

> **Note:** Metrics with `Pipeline, Region` dimensions (DroppedFrames, SvqTime) do not include `ChannelId` in their CloudWatch dimension set. These may return empty datapoints when queried with the default ChannelId dimension.

## Required Permissions

The following IAM permissions are required:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "MediaLiveChannelOperations",
      "Effect": "Allow",
      "Action": [
        "medialive:ListChannels",
        "medialive:DescribeChannel",
        "medialive:StartChannel",
        "medialive:StopChannel",
        "medialive:DescribeThumbnails",
        "medialive:DescribeSchedule",
        "medialive:BatchUpdateSchedule",
        "medialive:DeleteSchedule",
        "medialive:ListInputs",
        "medialive:DescribeInput"
      ],
      "Resource": "*"
    },
    {
      "Sid": "CloudWatchMetrics",
      "Effect": "Allow",
      "Action": [
        "cloudwatch:GetMetricStatistics"
      ],
      "Resource": "*"
    },
    {
      "Sid": "CloudWatchLogs",
      "Effect": "Allow",
      "Action": [
        "logs:FilterLogEvents"
      ],
      "Resource": "*"
    },
    {
      "Sid": "BedrockThumbnailAnalysis",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel"
      ],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
        "arn:aws:bedrock:*:*:inference-profile/*"
      ]
    }
  ]
}
```

> **Security Note:** For production use, scope `Resource` to specific channel ARNs, log group ARNs, and Bedrock model ARNs rather than using wildcards.

## Remote Deployment (Amazon Bedrock AgentCore)

The `main.py` + `src/app.py` entry point is for remote deployment via [Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock/latest/userguide/agentcore.html). It uses the same tool core but groups individual tools into composite tools for token reduction.

### Prerequisites

- [Amazon Bedrock AgentCore SDK](https://pypi.org/project/bedrock-agentcore/) installed (`pip install bedrock-agentcore`)
- Docker installed and running
- AWS credentials with permissions to create AgentCore resources

### Deploy with AgentCore CLI

The included `.bedrock_agentcore.yaml` provides the runtime configuration. On first deploy, AgentCore auto-creates the ECR repository, IAM roles, and runtime:

```bash
cd medialive-mcp-server

# Set your environment variables
export AWS_REGION=us-west-2
export AGENT_MODEL_ID=us.anthropic.claude-sonnet-4-6
export MEDIALIVE_DEFAULT_CHANNEL_ID=<YOUR_CHANNEL_ID>

# Deploy (creates ECR repo, builds container, registers runtime)
uv run agentcore launch --auto-update-on-conflict
```

After the first deploy, `.bedrock_agentcore.yaml` is populated with your account-specific values (runtime ARN, ECR repo, IAM roles). These are gitignored for public repos.

### Deploy with CDK (Production)

For production deployments, use AWS CDK following the pattern in [hydrolix-cdn-insights/cdk-hydrolix-data-assistant-agentcore-strands/](../hydrolix-cdn-insights/cdk-hydrolix-data-assistant-agentcore-strands/). The CDK stack should create:

- AgentCore Runtime with container configuration
- AgentCore Memory for conversation context
- IAM execution role with least-privilege permissions
- Runtime environment variables (`AGENT_MODEL_ID`, `MEDIALIVE_DEFAULT_CHANNEL_ID`, `THUMBNAIL_MODEL_ID`, `MEMORY_ID`)

A CDK stack for this project is planned for Phase 2.

### Composite Tools (Strands Agent)

The Strands Agent groups 15 individual tools into 6 composite tools for token reduction:

| Composite Tool | Actions | Individual Tools |
|----------------|---------|-----------------|
| `channel_management` | list, describe, start, stop, thumbnail | 5 tools |
| `channel_monitoring` | metrics, logs | 2 tools |
| `schedule_management` | describe, input_switch, immediate_switch, scte35, pause, unpause, delete | 7 tools |
| `channel_health_monitoring` | all_metrics, category_metrics, check_issues, metrics_table | 4 coordinator methods |
| `code_mode` | Any command + Python script | Sandboxed data processing |
| `current_time` | — | Current timestamp |

## Troubleshooting

### Common Issues

1. **No Channels Returned**
   - Verify AWS credentials: `aws sts get-caller-identity`
   - Check that the AWS region is set correctly
   - Ensure IAM permissions include `medialive:ListChannels`

2. **Thumbnail Analysis Fails**
   - Channel must be in RUNNING state with thumbnail generation enabled
   - Verify Bedrock access is configured in your region
   - Check IAM permissions include `bedrock:InvokeModel`

3. **No Metrics Data**
   - Channel must be or have been in RUNNING state during the queried time range
   - Verify CloudWatch permissions
   - MediaLive metrics may take a few minutes to appear after channel start
   - `DroppedFrames` and `SvqTime` use Pipeline+Region dimensions — empty results are expected when querying by ChannelId

4. **Connection Errors**
   - Verify AWS credentials are not expired
   - Check network connectivity to AWS APIs
   - Ensure the correct AWS region is configured

## Security Considerations

⚠️ **Important Security Notice**

This sample is provided for demonstration and educational purposes only. It is not recommended for production deployment without significant security hardening.

### Before Production Use

- Scope IAM permissions to specific channel ARNs rather than using wildcard resources
- Implement proper credential rotation and management
- Enable CloudTrail logging for all MediaLive API calls
- Review Bedrock model access policies
- Conduct security testing appropriate for your environment

## Contributing

Contributions are welcome. Please ensure:

1. Code follows existing patterns
2. New tools include proper documentation
3. Error handling is comprehensive
4. Tests cover new functionality

## License

This project is licensed under the Apache License 2.0 — see the [LICENSE](LICENSE) file for details.

## Related Projects

- [MediaConnect MCP Server](../mediaconnect-mcp-server/) — MCP server for MediaConnect flow management and monitoring
- [CMCD MCP Server](../cmcd-mcp-server/) — MCP server for CMCD streaming telemetry analysis
- [Hydrolix CDN Insights](../hydrolix-cdn-insights/) — Multi-agent CDN analytics with Amazon Bedrock AgentCore
- [AWS Elemental MediaLive Documentation](https://docs.aws.amazon.com/medialive/)
- [Model Context Protocol](https://modelcontextprotocol.io/)
