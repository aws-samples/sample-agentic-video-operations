# MediaLive MCP Server — Amazon Bedrock AgentCore Deployment with CDK

Deploy the MediaLive operations agent to [Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock/latest/userguide/agentcore.html) using [AWS CDK](https://aws.amazon.com/cdk/).

> **Working Directory**: Run all commands from the `medialive-mcp-server/cdk/` folder.

## Overview

This CDK stack deploys the MediaLive Strands Agent (`main.py` + `src/app.py`) as a containerized AgentCore runtime with the following resources:

- **AgentCore Memory**: Short-term conversation context with 7-day event expiration
- **AgentCore Runtime**: ARM64 container runtime hosting the agent
- **AgentCore Runtime Endpoint**: HTTP endpoint for invoking the agent
- **ECR Repository**: Auto-managed container image (built and pushed during `cdk deploy`)
- **IAM Execution Role**: Least-privilege permissions for MediaLive, CloudWatch, Bedrock, and AgentCore APIs

## Prerequisites

- AWS account with appropriate IAM permissions for CDK deployment
- Python 3.10+ (for the agent container)
- Node.js and npm (for CDK)
- Docker installed and running (required for building the container image)
- [AWS CDK installed](https://docs.aws.amazon.com/cdk/v2/guide/getting-started.html)
- AWS CDK bootstrapped in your target account/region (`cdk bootstrap`)

## Setup

Install CDK dependencies:

```bash
npm install
```

## Deploy

```bash
cdk deploy \
  --parameters BedrockModelId="us.anthropic.claude-sonnet-4-6" \
  --parameters ThumbnailModelId="us.anthropic.claude-haiku-4-5-20251001-v1:0" \
  --parameters DefaultChannelId="<YOUR_CHANNEL_ID>"
```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `BedrockModelId` | `us.anthropic.claude-sonnet-4-6` | Bedrock model for the agent LLM |
| `ThumbnailModelId` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Bedrock model for thumbnail analysis |
| `DefaultChannelId` | *(required)* | Your MediaLive channel ID |

### Stack Outputs

After deployment, the stack exports:

| Output | Description |
|--------|-------------|
| `MemoryId` | AgentCore Memory ID |
| `AgentRuntimeArn` | AgentCore Runtime ARN |
| `AgentEndpointName` | AgentCore Runtime Endpoint name |

## Retrieve Stack Outputs

```bash
export STACK_NAME=MediaLiveAgentCoreStack

export MEMORY_ID=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query "Stacks[0].Outputs[?OutputKey=='MemoryId'].OutputValue" \
  --output text)

export AGENT_RUNTIME_ARN=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query "Stacks[0].Outputs[?OutputKey=='AgentRuntimeArn'].OutputValue" \
  --output text)

export AGENT_ENDPOINT_NAME=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query "Stacks[0].Outputs[?OutputKey=='AgentEndpointName'].OutputValue" \
  --output text)

echo "MEMORY_ID: $MEMORY_ID"
echo "AGENT_RUNTIME_ARN: $AGENT_RUNTIME_ARN"
echo "AGENT_ENDPOINT_NAME: $AGENT_ENDPOINT_NAME"
```

## Local Testing

Before deploying, you can test the agent locally:

```bash
cd ../  # medialive-mcp-server/
pip install -r requirements.txt
python3 -m src.app
```

Then in another terminal:

```bash
export SESSION_ID=$(uuidgen)

curl -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"prompt": "List all MediaLive channels", "session_id": "'$SESSION_ID'"}'
```

## Run Tests

```bash
npm test
```

## Clean Up

To avoid unnecessary charges, delete the stack:

```bash
cdk destroy
```

> This will delete all resources including the AgentCore Runtime, Memory, Endpoint, ECR repository, and IAM role.

## License

This project is licensed under the Apache License 2.0.
