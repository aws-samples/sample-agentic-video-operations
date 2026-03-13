# MediaConnect MCP Server

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

A Model Context Protocol (MCP) server for managing and monitoring AWS Elemental MediaConnect flows. This server provides AI-powered tools for live video transport operations including flow management, CloudWatch metrics analysis, content quality monitoring, and visual thumbnail analysis using Amazon Bedrock.

## What is AWS Elemental MediaConnect?

[AWS Elemental MediaConnect](https://aws.amazon.com/mediaconnect/) is a reliable, secure, and flexible transport service for live video. It enables broadcasters and content owners to build live video workflows by connecting sources to destinations using protocols such as SRT, RIST, Zixi, RTP-FEC, and CDI. MediaConnect provides the reliability and security needed for both contribution and distribution of live video content.

## Architecture

This MCP server connects directly to the AWS MediaConnect and CloudWatch APIs to provide flow management and monitoring tools that can be used by AI assistants and other MCP clients.

```
┌─────────────────┐    ┌──────────────────┐    ┌──────────────────────────┐
│   MCP Client    │───▶│  MediaConnect    │───▶│  AWS APIs                │
│  (AI Assistant) │    │  MCP Server      │    │  ├─ MediaConnect         │
└─────────────────┘    └──────────────────┘    │  ├─ CloudWatch           │
                                               │  └─ Bedrock (thumbnails) │
                                               └──────────────────────────┘
```

## Features

### 🎬 Flow Management
- **List Flows** — Enumerate all MediaConnect flows in your account
- **Describe Flow** — Get detailed flow information with EventBridge-style health monitoring
- **Start/Stop Flow** — Control flow lifecycle
- **Source Metadata** — Retrieve transport stream details including codec, resolution, frame rate, and audio configuration

### 👁️ Visual Analysis
- **Thumbnail Analysis** — AI-powered visual analysis of flow thumbnails using Claude via Amazon Bedrock, providing content description and stream health assessment

### 📊 CloudWatch Monitoring (5 Categories)
- **Flow Health** — Bitrate, packet loss, ARQ recovery, disconnections, TR 101 290 Priority 1 & 2 compliance
- **Source Health** — Source connection status, dropped packets, merge warnings, FEC recovery
- **Output Health** — Output connections, disconnections, NDI receivers, CDI payload tracking
- **Media Health** — Network jitter, latency, connection attempts, consecutive drops
- **Content Quality** — Black frames, frozen frames, silent audio, missing streams, timecode presence

### 🔍 Issue Detection
- **Cross-Category Issue Detection** — Scan all monitoring categories for problems with severity classification
- **Metrics Table** — Export key metrics in tabular format for charting and visualization

## Prerequisites

- Python 3.11+
- AWS credentials configured (`aws configure`)
- AWS region set in your AWS config
- Required IAM permissions (see [Required Permissions](#required-permissions))
- Amazon Bedrock access (for thumbnail analysis with Claude)

## Setup

### 1. Set Up Virtual Environment

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate  # On macOS/Linux
# or
venv\Scripts\activate     # On Windows
```

### 2. Install Dependencies

```bash
cd sample-agentic-video-operations/mediaconnect-mcp-server
pip install -r requirements.txt
```

### 3. Verify the MCP Configuration File

The file at `mcp.json` should have the following content:

```json
{
  "mcpServers": {
    "mediaconnect-mcp": {
      "command": "python3",
      "args": ["server.py"],
      "cwd": "<DIRECTORY_PATH>",
      "env": {
        "FASTMCP_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

**Example mcp.json:**

```json
{
  "mcpServers": {
    "mediaconnect-mcp": {
      "command": "python3",
      "args": ["server.py"],
      "cwd": "/Users/johndoe/Downloads/sample-agentic-video-operations/mediaconnect-mcp-server",
      "env": {
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

**OR based on your directory structure:**

```bash
cp mcp.json ~/.q/mcp.json
```

### 2. Set Execute Permissions

```bash
chmod +x ~/.aws/amazonq/mcp.json
```

**OR based on your directory structure:**

```bash
chmod +x ~/.q/mcp.json
```

### 3. Running Amazon Q CLI

```bash
q chat
```

## Integration with Kiro

Add the MCP server configuration to your Kiro workspace:

1. Open the MCP configuration file at `.kiro/settings/mcp.json`
2. Add the MediaConnect MCP server entry:

```json
{
  "mcpServers": {
    "mediaconnect-mcp": {
      "command": "python3",
      "args": ["server.py"],
      "cwd": "/path/to/sample-agentic-video-operations/mediaconnect-mcp-server",
      "env": {
        "FASTMCP_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

## Integration with Claude Code

Add the MCP server to your Claude Code project configuration:

```bash
claude mcp add mediaconnect-mcp -- python3 /path/to/sample-agentic-video-operations/mediaconnect-mcp-server/server.py
```

Or add it manually to `.claude/settings.json`:

```json
{
  "mcpServers": {
    "mediaconnect-mcp": {
      "command": "python3",
      "args": ["/path/to/sample-agentic-video-operations/mediaconnect-mcp-server/server.py"],
      "env": {
        "FASTMCP_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

## Available Tools

### Flow Management

| Tool | Description | Parameters |
|------|-------------|------------|
| `list_flows` | List all MediaConnect flows | None |
| `describe_flow` | Get detailed flow info with health monitoring | `flow_arn` (required) |
| `start_flow` | Start a MediaConnect flow | `flow_arn` (required) |
| `stop_flow` | Stop a MediaConnect flow | `flow_arn` (required) |
| `describe_flow_source_metadata` | Get transport stream details (codec, resolution, audio) | `flow_arn` (required) |

### Visual Analysis

| Tool | Description | Parameters |
|------|-------------|------------|
| `describe_flow_thumbnail` | AI-powered visual analysis of flow thumbnail | `flow_arn` (required) |

### CloudWatch Monitoring

| Tool | Description | Parameters |
|------|-------------|------------|
| `get_all_metrics` | Get all metrics organized by category | `flow_arn` (required), `hours_back` (default: 1) |
| `get_flow_health_metrics` | Flow health: bitrate, packet loss, TR 101 290 | `flow_arn` (required), `hours_back` (default: 1) |
| `get_source_health_metrics` | Source health: connection, drops, merge status | `flow_arn` (required), `hours_back` (default: 1) |
| `get_output_health_metrics` | Output health: connections, NDI, CDI payloads | `flow_arn` (required), `hours_back` (default: 1) |
| `get_media_health_metrics` | Media health: jitter, latency, drops | `flow_arn` (required), `hours_back` (default: 1) |
| `get_content_quality_metrics` | Content quality: black/frozen frames, missing streams | `flow_arn` (required), `hours_back` (default: 1) |

### Issue Detection & Analysis

| Tool | Description | Parameters |
|------|-------------|------------|
| `check_flow_issues` | Cross-category issue detection with severity | `flow_arn` (required), `hours_back` (default: 24) |
| `get_metrics_table` | Metrics in tabular format for graphing | `flow_arn` (required), `hours_back` (default: 6) |

## Sample Questions

### Flow Management & Status
- "List all my MediaConnect flows"
- "Show me the status of all flows"
- "Describe the flow with ARN arn:aws:mediaconnect:us-west-2:123456789:flow:abc-123"
- "Start the production flow"
- "What's the source metadata for this flow?"

### Visual Content Analysis
- "Analyze the thumbnail of my active flow"
- "What does the video content look like for this flow?"
- "Describe the visual quality of the current stream"

### Health Monitoring
- "Show me all metrics for my flow from the past hour"
- "Get comprehensive health metrics for the last 2 hours"
- "What's the overall health status of my flow?"
- "Check flow health metrics for packet loss and bitrate"
- "Get source health metrics for the past day"
- "Check output health for connected receivers"
- "Check media health for jitter and latency"
- "Get content quality metrics — any black frames or frozen video?"

### Issue Detection & Troubleshooting
- "Check for issues in the past 24 hours"
- "Were there any connection problems today?"
- "Analyze flow problems across all categories"
- "Show me TR 101 290 compliance errors"
- "How is the SRT recovery performance?"

### Performance Analysis
- "Get metrics in table format for graphing"
- "Show me jitter and latency trends over 6 hours"
- "Compare source vs output bitrates"

## CloudWatch Metrics Reference

### Flow Health Metrics

| Metric | Description | Unit |
|--------|-------------|------|
| `BitRate` | Bitrate of incoming source video | Bits/Second |
| `Connected` | Source connection status (1=connected, 0=disconnected) | None |
| `Disconnections` | Number of source disconnections | Count |
| `DroppedPackets` | Packets lost during transit (before error correction) | Count |
| `PacketLossPercent` | Percentage of packets lost | Percent |
| `ARQRecovered` | Dropped packets recovered by ARQ | Count |
| `FECRecovered` | FEC packets lost and recovered | Count |
| `RoundTripTime` | Signal round-trip time | Milliseconds |
| `ContinuityCounter` | TR 101 290 P1: Continuity errors | Count |
| `PATError` | TR 101 290 P1: Program Association Table errors | Count |
| `PMTError` | TR 101 290 P1: Program Map Table errors | Count |
| `CRCError` | TR 101 290 P2: Data corruption errors | Count |

### Content Quality Metrics

| Metric | Description | Unit |
|--------|-------------|------|
| `BlackFramesBreaching` | Duration of black frames surpassing threshold | Count |
| `FrozenFramesBreaching` | Video unchanged longer than threshold | Count |
| `SilentAudioBreaching` | Silent audio exceeding threshold | Count |
| `AudioStreamMissing` | Expected audio stream not detected | Count |
| `VideoStreamMissing` | Expected video stream absent | Count |
| `TimecodePresent` | Valid timecode present in media stream | Count |

## Required Permissions

The following IAM permissions are required:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "mediaconnect:ListFlows",
        "mediaconnect:DescribeFlow",
        "mediaconnect:StartFlow",
        "mediaconnect:StopFlow",
        "mediaconnect:DescribeFlowSourceThumbnail",
        "mediaconnect:DescribeFlowSourceMetadata"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "cloudwatch:GetMetricStatistics"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel"
      ],
      "Resource": "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-20250514-v1:0"
    }
  ]
}
```

## Troubleshooting

### Common Issues

1. **No Flows Returned**:
   - Verify AWS credentials are configured (`aws sts get-caller-identity`)
   - Check that the AWS region is set correctly
   - Ensure IAM permissions include `mediaconnect:ListFlows`

2. **Thumbnail Analysis Fails**:
   - Flow must be in ACTIVE state with thumbnail generation enabled
   - Verify Bedrock access is configured in your region
   - Check IAM permissions include `bedrock:InvokeModel`

3. **No Metrics Data**:
   - Flow must be or have been in ACTIVE state during the queried time range
   - Verify CloudWatch permissions
   - MediaConnect metrics may take a few minutes to appear after flow activation

4. **Connection Errors**:
   - Verify AWS credentials are not expired
   - Check network connectivity to AWS APIs
   - Ensure the correct AWS region is configured

## Security Considerations

⚠️ **Important Security Notice**

This sample is provided for demonstration and educational purposes only. **It is not recommended for production deployment without significant security hardening.**

### Before Production Use:

- Review and restrict IAM permissions to specific flow ARNs rather than using wildcard resources
- Implement proper credential rotation and management
- Enable CloudTrail logging for all MediaConnect API calls
- Review Bedrock model access policies
- Conduct security testing appropriate for your environment

## Contributing

Contributions are welcome! Please ensure:

1. Code follows existing patterns
2. New tools include proper documentation
3. Error handling is comprehensive
4. Tests cover new functionality

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

## Related Projects

- [CMCD MCP Server](../cmcd-mcp-server/) — MCP server for CMCD streaming telemetry analysis
- [Hydrolix CDN Insights](../hydrolix-cdn-insights/) — Multi-agent CDN analytics with Amazon Bedrock AgentCore
- [AWS Elemental MediaConnect Documentation](https://docs.aws.amazon.com/mediaconnect/)
- [Model Context Protocol](https://modelcontextprotocol.io/)
