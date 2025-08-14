# CMCD MCP Server

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

A Model Context Protocol (MCP) server for analyzing Common Media Client Data (CMCD) streaming telemetry. This server provides AI-powered analytics tools for video streaming quality of experience (QoE) analysis using data stored in InfluxDB.

## What is CMCD?

Common Media Client Data (CMCD) is a specification that enables media players to convey streaming performance data to content delivery networks (CDNs) and origin servers. This data helps optimize streaming delivery and provides insights into playback quality.

## Architecture

This MCP server connects to InfluxDB containing CMCD telemetry data and provides structured analytics tools that can be used by AI assistants and other MCP clients to analyze streaming performance.

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   MCP Client    │───▶│   CMCD MCP       │───▶│    InfluxDB     │
│  (AI Assistant) │    │    Server        │    │ (CMCD Metrics)  │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

## Features

### 🎯 **Streaming Analytics**
- **Average Bitrate Analysis** - Calculate mean bitrates across time ranges with session/content filtering
- **Session Timeline Analysis** - Retrieve comprehensive session metrics and playback timelines
- **Buffer Event Detection** - Identify rebuffering incidents and low buffer events
- **Playback Error Analysis** - Detect buffer underruns, startup delays, and bitrate drops
- **Session Discovery** - Enumerate unique session and content identifiers

### 🔧 **Technical Capabilities**
- Real-time streaming telemetry analysis
- Flexible time range queries (`-1h`, `-24h`, `-7d`)
- Session and content ID filtering
- Structured JSON responses for AI consumption
- Comprehensive error detection and reporting

## Prerequisites

- Python 3.8+
- InfluxDB instance with CMCD data
- Valid InfluxDB credentials
- HLS video file (.m3u8) for testing CMCD data generation

## AWS Infrastructure Deployment

### Deploy the CMCD Pipeline

The complete CMCD analytics pipeline is deployed using AWS CloudFormation, which creates:

- **Amazon S3** - Video content storage
- **Amazon CloudFront** - CDN with CMCD log collection
- **AWS Lambda** - Log processing functions
- **Amazon Timestream for InfluxDB** - CMCD metrics storage
- **Amazon EC2** - Bastion host for secure database access
- **Amazon Kinesis Data Firehose** - Real-time log streaming

### Prerequisites for Deployment

- AWS CLI configured with appropriate permissions
- AWS account with sufficient service limits
- VPC with public and private subnets (or use default VPC)

### Deploy CloudFormation Stack

1. **Clone the Repository**:
   ```bash
   git clone <repository-url>
   cd cmcd-mcp
   ```

2. **Deploy the Stack**:
   ```bash
   aws cloudformation create-stack \
     --stack-name cmcd-analytics-pipeline \
     --template-body file://cloudfront-cmcd-kinesis.yaml \
     --parameters ParameterKey=InfluxDBPassword,ParameterValue=YourSecurePassword123 \
     --capabilities CAPABILITY_IAM
   ```

3. **Monitor Deployment**:
   ```bash
   aws cloudformation describe-stacks --stack-name cmcd-analytics-pipeline
   ```

4. **Get Stack Outputs**:
   ```bash
   aws cloudformation describe-stacks \
     --stack-name cmcd-analytics-pipeline \
     --query 'Stacks[0].Outputs'
   ```

### Key CloudFormation Outputs

| Output | Description | Usage |
|--------|-------------|-------|
| `InfluxDBEndpoint` | InfluxDB connection URL | MCP server configuration |
| `InfluxDBToken` | Database authentication token | MCP server configuration |
| `InfluxDBOrg` | Organization name | MCP server configuration |
| `S3BucketName` | Video content bucket | Upload HLS files |
| `CloudFrontDomain` | CDN domain | Video playback URLs |
| `BastionInstanceId` | EC2 bastion host ID | SSM connection |

## Quick Start

### 1. Set Up Virtual Environment

```bash
# Create virtual environment
python -m venv cmcd-mcp-env

# Activate virtual environment
source cmcd-mcp-env/bin/activate  # On macOS/Linux
# or
cmcd-mcp-env\Scripts\activate     # On Windows

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment

Create a `.env` file in the project root using values from your CloudFormation stack outputs:

```bash
INFLUXDB_URL=<InfluxDBEndpoint from CloudFormation outputs>
INFLUXDB_TOKEN=<InfluxDBToken from CloudFormation outputs>
INFLUXDB_ORG=<InfluxDBOrg from CloudFormation outputs>
VERIFY_SSL=false
```

### 3. Set Up Database Connection

#### Connect via AWS SSM (Bastion Host)

The InfluxDB instance is typically deployed in a private subnet and requires connection through a bastion host:

```bash
# Get bastion instance ID from CloudFormation outputs
# Connect to bastion host via SSM
aws ssm start-session --target <BastionInstanceId from CloudFormation outputs>

# Set up port forwarding for InfluxDB
aws ssm start-session --target <BastionInstanceId from CloudFormation outputs> \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["8086"],"localPortNumber":["8086"]}'
```

#### Retrieve InfluxDB Password

The InfluxDB password is stored in AWS Secrets Manager. Retrieve it using:

```bash
# Get the secret ARN from CloudFormation outputs
SECRET_ARN=$(aws cloudformation describe-stacks \
  --stack-name cmcd-analytics-pipeline \
  --query 'Stacks[0].Outputs[?OutputKey==`InfluxDBPasswordSecretArn`].OutputValue' \
  --output text)

# Retrieve the password
aws secretsmanager get-secret-value \
  --secret-id $SECRET_ARN \
  --query SecretString --output text | jq -r .password
```

#### Test Database Connection

Verify your InfluxDB connection before running the MCP server:

```bash
# Test connection using curl
curl -H "Authorization: Token $INFLUXDB_TOKEN" \
     -H "Accept: application/csv" \
     -G "$INFLUXDB_URL/api/v2/query" \
     --data-urlencode "org=$INFLUXDB_ORG" \
     --data-urlencode 'q=buckets()'

# Or use the InfluxDB CLI
influx bucket list --host $INFLUXDB_URL --token $INFLUXDB_TOKEN --org $INFLUXDB_ORG
```



## Data Schema

The server expects CMCD data in InfluxDB with the following structure:

| Component | Value | Description |
|-----------|-------|-------------|
| **Bucket** | `cmcd-metrics` | InfluxDB bucket containing CMCD data |
| **Measurement** | `cloudfront_logs` | Primary measurement name |

### CMCD Fields

| Field | Description | Unit |
|-------|-------------|------|
| `cmcd_bl` | Buffer length | milliseconds |
| `cmcd_br` | Encoded bitrate | kbps |
| `cmcd_d` | Segment duration | milliseconds |
| `cmcd_su` | Startup flag | boolean |
| `cmcd_tb` | Top bitrate | kbps |
| `cmcd_bs` | Buffer starved flag | boolean |
| `cmcd_mtp` | Measured throughput | kbps |

### Tags

| Tag | Description |
|-----|-------------|
| `cmcd_sid` | Session identifier |
| `cmcd_cid` | Content identifier |
| `edge_location` | CDN edge location |

## Available Tools

### `get_average_bitrate`
Calculates average bitrate over specified time ranges with optional filtering.

**Parameters:**
- `time_range` (default: "-24h"): Time range for analysis
- `cmcd_sid` (optional): Filter by session ID
- `cmcd_cid` (optional): Filter by content ID

### `get_session_details`
Retrieves comprehensive metrics timeline for a specific session.

**Parameters:**
- `cmcd_sid` (required): Session ID to analyze
- `time_range` (default: "-24h"): Time range for analysis

### `analyze_buffer_events`
Identifies potential rebuffering events based on buffer level thresholds.

**Parameters:**
- `time_range` (default: "-24h"): Time range for analysis
- `cmcd_sid` (optional): Filter by session ID
- `threshold_ms` (default: 500): Buffer level threshold in milliseconds

### `identify_playback_errors`
Detects various playback issues including buffer underruns and startup delays.

**Parameters:**
- `time_range` (default: "-24h"): Time range for analysis
- `cmcd_sid` (optional): Filter by session ID

### `list_session_and_content_ids`
Enumerates unique session and content identifiers in the dataset.

**Parameters:**
- `time_range` (default: "-24h"): Time range for analysis
- `limit` (default: 100): Maximum number of IDs to return

## Generating CMCD Data

### Upload HLS Content

The CloudFormation template creates an S3 bucket for video content accessible via CloudFront:

1. **Upload HLS Video Files**:
   ```bash
   # Upload your HLS playlist and segments to the S3 bucket
   # Use the S3BucketName from CloudFormation outputs
   aws s3 cp your-video.m3u8 s3://<S3BucketName from CloudFormation outputs>/videos/
   aws s3 cp video-segments/ s3://<S3BucketName from CloudFormation outputs>/videos/ --recursive
   ```

2. **Access via CloudFront**:
   ```
   https://<CloudFrontDomain from CloudFormation outputs>/videos/your-video.m3u8
   ```

### Use the Sample HTML Player

1. **Configure the Player**:
   - Open `web/index.html` in the project
   - Update the video source URL with your CloudFront domain:
   ```javascript
   // Replace the source URL in web/index.html
   src: "https://<CloudFrontDomain from CloudFormation outputs>/videos/your-video.m3u8"
   ```

2. **Host the Player**:
   ```bash
   # Serve the HTML file locally
   cd web/
   python -m http.server 8000
   # Open http://localhost:8000 in your browser
   ```

3. **Generate CMCD Data**:
   - Play the video in the browser
   - The player automatically sends CMCD parameters to CloudFront
   - Streaming telemetry data will be collected and processed into InfluxDB

## Integration with Amazon Q CLI

To use this MCP server with Amazon Q CLI, you need to configure the MCP client settings:

### Option 1: Copy to Q CLI Directory

```bash
# Copy the MCP configuration to Q CLI directory
cp mcp.json ~/.q/mcp.json
```

### Option 2: Create .amazonq Directory

```bash
# Create .amazonq directory in your project root
mkdir .amazonq
cp mcp.json .amazonq/mcp.json
```

### MCP Configuration (mcp.json)

```json
{
  "mcpServers": {
    "cmcd-analytics": {
      "command": "./cmcd-mcp-env/bin/python",
      "args": ["mcp/cmcd_server.py"],
      "env": {
        "INFLUXDB_URL": "your-influxdb-url",
        "INFLUXDB_TOKEN": "your-token",
        "INFLUXDB_ORG": "your-org"
      }
    }
  }
}
```

### Running Amazon Q CLI

Ensure Amazon Q CLI also runs in the virtual environment:

```bash
# Activate virtual environment
source cmcd-mcp-env/bin/activate

# Run Q CLI
q dev
```

Once configured, Amazon Q can analyze your CMCD streaming data and provide insights about:

- Streaming performance trends
- Quality issues and their root causes
- User experience metrics
- Session and content correlations

## Troubleshooting

### Common Issues

1. **Connection Errors**: 
   - Verify InfluxDB URL and credentials
   - Ensure SSM port forwarding is active
   - Check bastion host security groups allow port 8086

2. **No Data Returned**: 
   - Check bucket name and measurement structure
   - Verify CMCD data is being generated by video player
   - Confirm CloudFront logs are being processed into InfluxDB

3. **Schema Errors**: 
   - Ensure CMCD fields match expected format
   - Verify tag names use `cmcd_sid` and `cmcd_cid`

4. **SSM Connection Issues**:
   ```bash
   # Check SSM agent status using bastion instance ID from CloudFormation
   aws ssm describe-instance-information --filters "Key=InstanceIds,Values=<BastionInstanceId>"
   
   # Verify IAM permissions for SSM
   aws sts get-caller-identity
   ```

### Logging

Logs are written to `cmcd_server.log` with rotation at 10MB. Check logs for detailed error information.

## Contributing

Contributions are welcome! Please ensure:

1. Code follows existing patterns
2. New tools include proper documentation
3. Error handling is comprehensive
4. Tests cover new functionality

## Security Considerations

⚠️ **Important Security Notice**

This sample is provided for demonstration and educational purposes only. **It is not recommended for production deployment without significant security hardening and customization.**

### Before Production Use:

- **Review and adapt all security configurations** to meet your organization's security standards and compliance requirements
- **Change all default passwords and credentials** - The template includes placeholder passwords that must be updated
- **Implement proper network segmentation** and review all security group rules for your specific use case
- **Enable comprehensive logging and monitoring** beyond what's provided in this sample
- **Conduct thorough security testing** including penetration testing and vulnerability assessments
- **Review IAM permissions** and apply the principle of least privilege for your specific requirements
- **Implement proper backup and disaster recovery** procedures for production data
- **Ensure compliance** with relevant industry standards and regulations (SOC 2, GDPR, HIPAA, etc.)

### Security Features Included:

- KMS encryption for S3, Kinesis, and Secrets Manager
- WAF protection for CloudFront distribution
- VPC isolation for InfluxDB instance
- Secrets Manager for credential management with rotation
- TLS 1.2 minimum for CloudFront
- Private subnets for sensitive resources

**This sample should be thoroughly reviewed, tested, and customized by qualified security professionals before any production use.**

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

## Related Projects

- [CloudFront CMCD Real-time Dashboard](https://github.com/aws-samples/cloudfront-cmcd-realtime-dashboard)
- [CMCD Specification (CTA-5004)](https://www.cta.tech/Resources/Standards)
- [Model Context Protocol](https://modelcontextprotocol.io/)

---

**Note**: This server focuses on analytics and does not include direct InfluxDB query capabilities. For custom Flux queries, consider the companion InfluxDB MCP server.