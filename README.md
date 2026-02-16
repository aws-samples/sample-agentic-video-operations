<div align="center">
  <img src="./images/genai.png" alt="Agentic Intelligent Media Operations" width="120">
  <h1>Agentic Intelligent Media Operations</h1>

  [![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
</div>

Media companies — whether delivering live broadcasts, on-demand streaming, or hybrid workflows — face challenges in ensuring consistently high levels of operational performance across complex delivery chains. Quality issues can lead audiences to abandon a platform, yet identifying root causes across signal and content delivery paths can take hours. Traditional monitoring fails to connect technical performance with user experience and business impact, leaving teams blind to which issues drive the most churn and revenue loss.

This repository hosts sample projects that showcase **intelligent observability** for media operations — spanning streaming, broadcast, and content delivery. Each sample demonstrates how specialized AI agents can continuously monitor quality across the media supply chain, identify root causes within seconds, generate specific resolution paths, and enable proactive experience optimization.

> **Note:** These samples are provided for demonstration and educational purposes. They are not production-ready without security hardening and customization for your environment.

## Samples

| | Sample | Description | Key Technologies |
|:---:|--------|-------------|------------------|
| <img src="./images/genai.png" width="40"> | **[cmcd-mcp-server](./cmcd-mcp-server/)** | MCP server for analyzing Common Media Client Data (CMCD) streaming telemetry. AI-powered analytics tools for video streaming QoE analysis using InfluxDB. | MCP, CMCD, InfluxDB, CloudFront, Kinesis |
| <img src="./images/agentcore.png" width="40"> | **[hydrolix-cdn-insights](./hydrolix-cdn-insights/)** | Generative AI assistant for CDN and streaming video analytics using Hydrolix time-series data. Natural language interface for real-time performance insights powered by Amazon Bedrock AgentCore. | Strands Agents SDK, Amazon Bedrock AgentCore, Hydrolix, CDK, Amplify |

## Getting Started

Each sample is self-contained with its own README, dependencies, and deployment instructions. Navigate to the sample folder to get started:

```bash
git clone https://github.com/aws-samples/sample-agentic-video-operations
cd sample-agentic-video-operations

# Pick a sample
cd cmcd-mcp-server      # CMCD MCP analytics server
cd hydrolix-cdn-insights # Hydrolix CDN insights with AgentCore
```

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This project is licensed under the Apache-2.0 License. See the [LICENSE](LICENSE) file for details.
