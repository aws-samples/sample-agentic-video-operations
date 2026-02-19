# Hydrolix CDN Insights - Amazon Bedrock AgentCore Deployment with CDK

Deploy the complete infrastructure for **Hydrolix CDN Insights** using **[AWS Cloud Development Kit (CDK)](https://aws.amazon.com/cdk/)** and **[Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock/latest/userguide/agentcore.html)**.

> [!NOTE]
> **Working Directory**: Make sure you are in the `cdk-hydrolix-data-assistant-agentcore-strands/` folder before starting this tutorial. All commands in this guide should be executed from this directory.

## Overview

This CDK stack deploys a complete Hydrolix CDN Insights assistant powered by Amazon Bedrock AgentCore with the following components:

### Amazon Bedrock AgentCore Resources

- **AgentCore Memory**: Short-term memory for maintaining conversation context with 7-day event expiration
- **AgentCore Runtime**: Container-based runtime hosting the Strands Agent with ARM64 architecture
- **AgentCore Runtime Endpoint**: HTTP endpoint for invoking Hydrolix CDN Insights

### Data and Configuration Infrastructure

- **Amazon DynamoDB**: Table for tracking SQL query results with pay-per-request billing
- **AWS Secrets Manager**: Secure storage for Hydrolix connection credentials
- **IAM Roles**: Permissions for AgentCore to access Bedrock, DynamoDB, and Secrets Manager

> [!IMPORTANT]
> Remember to clean up resources after testing to avoid unnecessary costs by following the clean-up steps provided.

## Prerequisites

Before you begin, ensure you have:

* AWS Account and appropriate IAM permissions for services deployment
* **Development Environment**:
  * Python 3.10 or later installed
  * Node.js and npm installed
  * Docker installed and running (required for building the agent container image)
  * **[AWS CDK Installed](https://docs.aws.amazon.com/cdk/v2/guide/getting-started.html)**
* **Hydrolix Account**: Access to a Hydrolix cluster with CDN/streaming video data

## Setup MCP Hydrolix

Before deploying the infrastructure, you need to set up the **[Hydrolix MCP Server](https://github.com/hydrolix/mcp-hydrolix)** (Model Context Protocol) package that enables the agent to query Hydrolix data.

1. Clone the MCP Hydrolix repository:

```bash
git clone https://github.com/hydrolix/mcp-hydrolix.git
```

2. Move the `mcp_hydrolix` package to the agent's MCP directory:

```bash
mv mcp-hydrolix/mcp_hydrolix hydrolix-data-assistant-agentcore-strands/src/mcp/
```

3. Clean up the cloned repository (optional):

```bash
rm -rf mcp-hydrolix
```

The `mcp_hydrolix` package is now integrated into your agent project and will be included in the Docker container during deployment.

## AWS Deployment

Navigate to the CDK project folder and install dependencies:

```bash
npm install
```

Deploy the infrastructure with parameter values:

```bash
cdk deploy \
  --parameters BedrockModelId="global.anthropic.claude-haiku-4-5-20251001-v1:0" \
  --parameters HydrolixTable="your_database.your_table"
```

Default Parameters:
- **BedrockModelId**: "global.anthropic.claude-haiku-4-5-20251001-v1:0" - Bedrock model ID for the agent
- **HydrolixTable**: "ibc.demo" - Hydrolix table name (format: database.table)

### Deployed Resources

**AgentCore Resources:**
- AgentCore Memory with 7-day event expiration
- AgentCore Runtime (container-based, ARM64)
- AgentCore Runtime Endpoint
- ECR repository with agent container image

**Data Infrastructure:**
- DynamoDB table for SQL query results
- Secrets Manager for Hydrolix credentials

**Runtime Environment Variables:**
The AgentCore Runtime automatically receives these environment variables:
- `MEMORY_ID`: AgentCore Memory ID
- `BEDROCK_MODEL_ID`: Bedrock model ID for the agent
- `HYDROLIX_SECRET_ARN`: Hydrolix Secrets Manager ARN
- `HYDROLIX_TABLE`: Hydrolix table name (e.g., "ibc.demo")
- `QUESTION_ANSWERS_TABLE`: DynamoDB table name for query results

### Stack Outputs

After deployment, the stack exports:
- `MemoryId`: AgentCore Memory ID
- `QuestionAnswersTableName`: DynamoDB table name
- `QuestionAnswersTableArn`: DynamoDB table ARN
- `AgentRuntimeArn`: AgentCore runtime ARN
- `AgentEndpointName`: AgentCore runtime endpoint name
- `HydrolixSecretArn`: Hydrolix credentials secret ARN
- `HydrolixTableName`: Hydrolix table name

> [!IMPORTANT] 
> Enhance AI safety and compliance by implementing **[Amazon Bedrock Guardrails](https://aws.amazon.com/bedrock/guardrails/)** for your AI applications with the seamless integration offered by **[Strands Agents SDK](https://strandsagents.com/latest/user-guide/safety-security/guardrails/)**.

## Set Up Environment Variables

After deployment, set up the required environment variables for local testing:

```bash
# Set the stack name environment variable
export STACK_NAME=CdkHydrolixDataAssistantAgentcoreStrandsStack

# Retrieve the output values and store them in environment variables

# Configuration parameters
export BEDROCK_MODEL_ID=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --query "Stacks[0].Parameters[?ParameterKey=='BedrockModelId'].ParameterValue" --output text)
export HYDROLIX_TABLE=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --query "Stacks[0].Parameters[?ParameterKey=='HydrolixTable'].ParameterValue" --output text)

# AgentCore resources
export MEMORY_ID=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --query "Stacks[0].Outputs[?OutputKey=='MemoryId'].OutputValue" --output text)
export AGENT_RUNTIME_ARN=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --query "Stacks[0].Outputs[?OutputKey=='AgentRuntimeArn'].OutputValue" --output text)
export AGENT_ENDPOINT_NAME=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --query "Stacks[0].Outputs[?OutputKey=='AgentEndpointName'].OutputValue" --output text)

# DynamoDB resources
export QUESTION_ANSWERS_TABLE=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --query "Stacks[0].Outputs[?OutputKey=='QuestionAnswersTableName'].OutputValue" --output text)

# Hydrolix configuration
export HYDROLIX_SECRET_ARN=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --query "Stacks[0].Outputs[?OutputKey=='HydrolixSecretArn'].OutputValue" --output text)

cat << EOF
# Stack Configuration
STACK_NAME: ${STACK_NAME}
BEDROCK_MODEL_ID: ${BEDROCK_MODEL_ID}
HYDROLIX_TABLE: ${HYDROLIX_TABLE}

# AgentCore Resources
MEMORY_ID: ${MEMORY_ID}
AGENT_RUNTIME_ARN: ${AGENT_RUNTIME_ARN}
AGENT_ENDPOINT_NAME: ${AGENT_ENDPOINT_NAME}

# DynamoDB Resources
QUESTION_ANSWERS_TABLE: ${QUESTION_ANSWERS_TABLE}

# Hydrolix Resources
HYDROLIX_SECRET_ARN: ${HYDROLIX_SECRET_ARN}
EOF
```

### Hydrolix Configuration

The stack automatically creates a Secrets Manager secret with placeholder Hydrolix credentials. After deployment, update the secret with your actual Hydrolix connection details:

1. Find the secret ARN in the stack outputs (`HydrolixSecretArn`)

2. Update the secret values in AWS Secrets Manager console or via CLI:

```bash
aws secretsmanager put-secret-value \
  --secret-id "$HYDROLIX_SECRET_ARN" \
  --secret-string '{
    "HYDROLIX_HOST": "your-actual-hydrolix-host.example.com",
    "HYDROLIX_PORT": "8088",
    "HYDROLIX_USER": "your-actual-username",
    "HYDROLIX_PASSWORD": "your-actual-password"
  }'
```

3. The Hydrolix agents will use these credentials when querying time-series data.

## Local Testing

Before deploying to AWS, you can test Hydrolix CDN Insights locally to verify functionality:

1. Navigate to the agent folder and start the local agent server:

```bash
cd data-analyst-assistant-agentcore-strands
python3 app.py
```

This launches a local server on port 8080 that simulates the AgentCore runtime environment.

2. In a different terminal, create a session ID for conversation tracking:

```bash
export SESSION_ID=$(uuidgen)
```

3. Test the agent with example queries using curl:

**Hello / Introduction:**

```bash
curl -X POST http://localhost:8080/invocations \
-H "Content-Type: application/json" \
-d '{"prompt": "Hello! What data do you have access to and what kind of analysis can you help me with?", "session_id": "'$SESSION_ID'", "last_k_turns": 20}'
```

**Hydrolix Agent (general time-series exploration):**

```bash
curl -X POST http://localhost:8080/invocations \
-H "Content-Type: application/json" \
-d '{"prompt": "How many total requests have been recorded and what are the top 5 countries by traffic volume?", "session_id": "'$SESSION_ID'", "last_k_turns": 20}'
```

```bash
curl -X POST http://localhost:8080/invocations \
-H "Content-Type: application/json" \
-d '{"prompt": "Show me the request volume trend per minute for the last 30 minutes, broken down by HTTP status code", "session_id": "'$SESSION_ID'", "last_k_turns": 20}'
```

**Cache & Origin Agent (CDN infrastructure performance):**

```bash
curl -X POST http://localhost:8080/invocations \
-H "Content-Type: application/json" \
-d '{"prompt": "What is the current cache hit rate and which edge locations have the lowest cache efficiency?", "session_id": "'$SESSION_ID'", "last_k_turns": 20}'
```

```bash
curl -X POST http://localhost:8080/invocations \
-H "Content-Type: application/json" \
-d '{"prompt": "Compare origin TTFB vs edge TTFB for cache misses and show the error rate breakdown by status code", "session_id": "'$SESSION_ID'", "last_k_turns": 20}'
```

**QoE Analysis Agent (viewer quality of experience):**

```bash
curl -X POST http://localhost:8080/invocations \
-H "Content-Type: application/json" \
-d '{"prompt": "Are there any buffer starvation events? Show me the rebuffering ratio by country", "session_id": "'$SESSION_ID'", "last_k_turns": 20}'
```

```bash
curl -X POST http://localhost:8080/invocations \
-H "Content-Type: application/json" \
-d '{"prompt": "What is the average encoded bitrate vs measured throughput? Are viewers getting the top available quality?", "session_id": "'$SESSION_ID'", "last_k_turns": 20}'
```

**Cross-agent analysis (spans multiple agent topics):**

```bash
curl -X POST http://localhost:8080/invocations \
-H "Content-Type: application/json" \
-d '{"prompt": "Give me a full health check: cache hit rate, origin latency, error rates, and viewer QoE metrics including rebuffering and bitrate quality", "session_id": "'$SESSION_ID'", "last_k_turns": 20}'
```

**Conversation summary:**

```bash
curl -X POST http://localhost:8080/invocations \
-H "Content-Type: application/json" \
-d '{"prompt": "Give me a summary of our conversation", "session_id": "'$SESSION_ID'", "last_k_turns": 20}'
```

## Invoking the Agent

Once deployed and Hydrolix credentials are configured, you can invoke the agent using the AgentCore Runtime Endpoint. The endpoint name is available in the stack outputs as `AgentEndpointName`.

## Next Step

You can now proceed to the **[Front-End Implementation with Amplify](../amplify-hydrolix-data-assistant-agentcore-strands/)**.

## Cleaning-up Resources (Optional)

To avoid unnecessary charges, delete the CDK stack:

```bash
cdk destroy
```

## License

This project is licensed under the Apache-2.0 License.
