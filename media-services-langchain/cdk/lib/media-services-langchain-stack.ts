/**
 * CDK Stack: Media Services LangChain Multi-Agent System
 *
 * Deploys 3 AgentCore Runtimes (Coordinator, EML, EMX) with:
 * - Shared AgentCore Memory (namespace isolation via actor_id)
 * - Separate IAM roles per runtime (least-privilege)
 * - OpenTelemetry observability enabled
 * - Code Interpreter access for EML/EMX
 */

import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as iam from "aws-cdk-lib/aws-iam";
import * as ecr_assets from "aws-cdk-lib/aws-ecr-assets";
import * as path from "path";
import { aws_bedrockagentcore as bedrockagentcore } from "aws-cdk-lib";

export class MediaServicesLangChainStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ================================
    // PARAMETERS
    // ================================

    const bedrockModelId = new cdk.CfnParameter(this, "BedrockModelId", {
      type: "String",
      description: "Bedrock model ID for all agents",
      default: "us.anthropic.claude-sonnet-4-6",
    });

    // ================================
    // SHARED MEMORY
    // ================================

    const uniqueSuffix = cdk.Names.uniqueId(this)
      .slice(-8)
      .toLowerCase()
      .replace(/[^a-z0-9]/g, "");

    const sharedMemory = new bedrockagentcore.CfnMemory(this, "SharedMemory", {
      name: `MediaServicesLangChain_${uniqueSuffix}`,
      eventExpiryDuration: 7,
      description:
        "Shared memory for LangChain multi-agent system. Namespace isolation via actor_id.",
    });

    // ================================
    // IAM ROLES (3 separate, least-privilege)
    // ================================

    const basePolicyStatements = [
      new iam.PolicyStatement({
        sid: "ECRAccess",
        actions: [
          "ecr:BatchCheckLayerAvailability",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
          "ecr:GetAuthorizationToken",
        ],
        resources: ["*"],
      }),
      new iam.PolicyStatement({
        sid: "CloudWatchLogs",
        actions: [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:DescribeLogStreams",
          "logs:DescribeLogGroups",
        ],
        resources: [
          `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/runtimes/*`,
          `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*`,
        ],
      }),
      new iam.PolicyStatement({
        sid: "XRayTracing",
        actions: [
          "xray:PutTraceSegments",
          "xray:PutTelemetryRecords",
          "xray:GetSamplingRules",
          "xray:GetSamplingTargets",
        ],
        resources: ["*"],
      }),
      new iam.PolicyStatement({
        sid: "CloudWatchMetrics",
        actions: ["cloudwatch:PutMetricData"],
        resources: ["*"],
        conditions: {
          StringEquals: { "cloudwatch:namespace": "bedrock-agentcore" },
        },
      }),
      new iam.PolicyStatement({
        sid: "BedrockModelInvocation",
        actions: ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
        resources: [
          "arn:aws:bedrock:*::foundation-model/*",
          `arn:aws:bedrock:*:*:inference-profile/*`,
        ],
      }),
      new iam.PolicyStatement({
        sid: "AgentCoreMemory",
        actions: [
          "bedrock-agentcore:GetMemoryRecord",
          "bedrock-agentcore:GetMemory",
          "bedrock-agentcore:RetrieveMemoryRecords",
          "bedrock-agentcore:CreateEvent",
          "bedrock-agentcore:ListSessions",
          "bedrock-agentcore:ListEvents",
          "bedrock-agentcore:GetEvent",
          "bedrock-agentcore:ListMemoryRecords",
        ],
        resources: ["*"],
      }),
      new iam.PolicyStatement({
        sid: "WorkloadIdentity",
        actions: [
          "bedrock-agentcore:GetWorkloadAccessToken",
          "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
          "bedrock-agentcore:GetWorkloadAccessTokenForUserId",
        ],
        resources: [
          `arn:aws:bedrock-agentcore:${this.region}:${this.account}:workload-identity-directory/default`,
          `arn:aws:bedrock-agentcore:${this.region}:${this.account}:workload-identity-directory/default/workload-identity/*`,
        ],
      }),
    ];

    const trustPolicy = {
      Version: "2012-10-17",
      Statement: [
        {
          Effect: "Allow",
          Principal: { Service: "bedrock-agentcore.amazonaws.com" },
          Action: ["sts:AssumeRole", "sts:TagSession"],
        },
      ],
    };

    // --- EML Role (AWS Elemental MediaLive) ---
    const emlRole = new iam.Role(this, "EMLRole", {
      roleName: `AgentCore-EML-LangChain-${this.region}`,
      assumedBy: new iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
      inlinePolicies: {
        EMLPolicy: new iam.PolicyDocument({
          statements: [
            ...basePolicyStatements,
            new iam.PolicyStatement({
              sid: "MediaLiveReadOperations",
              actions: [
                "medialive:ListChannels",
                "medialive:DescribeChannel",
                "medialive:DescribeThumbnails",
                "medialive:DescribeSchedule",
                "medialive:ListInputs",
                "medialive:DescribeInput",
                "medialive:DescribeInputDevice",
                "medialive:ListInputDevices",
              ],
              resources: ["*"],
            }),
            new iam.PolicyStatement({
              sid: "MediaLiveWriteOperations",
              actions: [
                "medialive:StartChannel",
                "medialive:StopChannel",
                "medialive:BatchUpdateSchedule",
                "medialive:DeleteSchedule",
              ],
              resources: ["*"],
            }),
            new iam.PolicyStatement({
              sid: "CloudWatchMetricsRead",
              actions: ["cloudwatch:GetMetricStatistics"],
              resources: ["*"],
            }),
            new iam.PolicyStatement({
              sid: "CloudWatchLogsRead",
              actions: ["logs:FilterLogEvents"],
              resources: ["*"],
            }),
            new iam.PolicyStatement({
              sid: "BedrockThumbnailAnalysis",
              actions: ["bedrock:InvokeModel"],
              resources: [
                "arn:aws:bedrock:*::foundation-model/*",
                `arn:aws:bedrock:*:*:inference-profile/*`,
              ],
            }),
          ],
        }),
      },
    });
    (emlRole.node.defaultChild as iam.CfnRole).addPropertyOverride(
      "AssumeRolePolicyDocument",
      trustPolicy
    );

    // --- EMX Role (AWS Elemental MediaConnect) ---
    const emxRole = new iam.Role(this, "EMXRole", {
      roleName: `AgentCore-EMX-LangChain-${this.region}`,
      assumedBy: new iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
      inlinePolicies: {
        EMXPolicy: new iam.PolicyDocument({
          statements: [
            ...basePolicyStatements,
            new iam.PolicyStatement({
              sid: "MediaConnectReadOperations",
              actions: [
                "mediaconnect:ListFlows",
                "mediaconnect:DescribeFlow",
                "mediaconnect:ListEntitlements",
                "mediaconnect:DescribeOffering",
                "mediaconnect:ListGatewayInstances",
                "mediaconnect:DescribeGatewayInstance",
                "mediaconnect:ListBridges",
                "mediaconnect:DescribeBridge",
              ],
              resources: ["*"],
            }),
            new iam.PolicyStatement({
              sid: "MediaConnectWriteOperations",
              actions: [
                "mediaconnect:StartFlow",
                "mediaconnect:StopFlow",
                "mediaconnect:AddFlowOutputs",
                "mediaconnect:RemoveFlowOutput",
                "mediaconnect:UpdateFlow",
                "mediaconnect:UpdateFlowOutput",
                "mediaconnect:UpdateFlowSource",
              ],
              resources: ["*"],
            }),
            new iam.PolicyStatement({
              sid: "CloudWatchMetricsRead",
              actions: ["cloudwatch:GetMetricStatistics"],
              resources: ["*"],
            }),
            new iam.PolicyStatement({
              sid: "BedrockThumbnailAnalysis",
              actions: ["bedrock:InvokeModel"],
              resources: [
                "arn:aws:bedrock:*::foundation-model/*",
                `arn:aws:bedrock:*:*:inference-profile/*`,
              ],
            }),
          ],
        }),
      },
    });
    (emxRole.node.defaultChild as iam.CfnRole).addPropertyOverride(
      "AssumeRolePolicyDocument",
      trustPolicy
    );

    // ================================
    // DOCKER IMAGES
    // ================================

    // Build context is the REPO ROOT so Dockerfiles can COPY from both
    // media-services-langchain/ and sibling directories (medialive-mcp-server/, mediaconnect-mcp-server/)
    const repoRoot = path.join(__dirname, "../../..");

    const dockerExclude = [
      "**/.git",
      "**/cdk.out",
      "**/node_modules",
      "**/__pycache__",
      "**/.pytest_cache",
      "**/.venv",
      "**/venv",
      ".kiro",
      ".claude",
      "images",
      "hydrolix-cdn-insights/amplify-*",
      "hydrolix-cdn-insights/cdk-*",
      "cmcd-mcp-server",
      "mcp-eml-reference",
    ];

    const coordinatorImage = new ecr_assets.DockerImageAsset(
      this,
      "CoordinatorImage",
      {
        directory: repoRoot,
        file: "media-services-langchain/coordinator/Dockerfile",
        platform: ecr_assets.Platform.LINUX_ARM64,
        exclude: dockerExclude,
      }
    );

    const emlImage = new ecr_assets.DockerImageAsset(this, "EMLImage", {
      directory: repoRoot,
      file: "media-services-langchain/eml/Dockerfile",
      platform: ecr_assets.Platform.LINUX_ARM64,
      exclude: dockerExclude,
    });

    const emxImage = new ecr_assets.DockerImageAsset(this, "EMXImage", {
      directory: repoRoot,
      file: "media-services-langchain/emx/Dockerfile",
      platform: ecr_assets.Platform.LINUX_ARM64,
      exclude: dockerExclude,
    });

    // ================================
    // RUNTIMES (EML and EMX first — coordinator needs their ARNs)
    // ================================

    const emlRuntime = new bedrockagentcore.CfnRuntime(this, "EMLRuntime", {
      agentRuntimeName: `EML_LangChain_${uniqueSuffix}`,
      agentRuntimeArtifact: {
        containerConfiguration: { containerUri: emlImage.imageUri },
      },
      networkConfiguration: { networkMode: "PUBLIC" },
      roleArn: emlRole.roleArn,
      description: "EML MediaLive specialist (LangChain/LangGraph)",
      environmentVariables: {
        MEMORY_ID: sharedMemory.attrMemoryId,
        AGENT_MODEL_ID: bedrockModelId.valueAsString,
        AGENT_NAME: "eml",
        AWS_REGION: this.region,
      },
    });
    emlRuntime.addDependency(sharedMemory);

    const emxRuntime = new bedrockagentcore.CfnRuntime(this, "EMXRuntime", {
      agentRuntimeName: `EMX_LangChain_${uniqueSuffix}`,
      agentRuntimeArtifact: {
        containerConfiguration: { containerUri: emxImage.imageUri },
      },
      networkConfiguration: { networkMode: "PUBLIC" },
      roleArn: emxRole.roleArn,
      description: "EMX MediaConnect specialist (LangChain/LangGraph)",
      environmentVariables: {
        MEMORY_ID: sharedMemory.attrMemoryId,
        AGENT_MODEL_ID: bedrockModelId.valueAsString,
        AGENT_NAME: "emx",
        AWS_REGION: this.region,
      },
    });
    emxRuntime.addDependency(sharedMemory);

    // --- Coordinator Role (needs EML/EMX ARNs for InvokeAgentRuntime) ---
    const coordinatorRole = new iam.Role(this, "CoordinatorRole", {
      roleName: `AgentCore-Coordinator-LangChain-${this.region}`,
      assumedBy: new iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
      inlinePolicies: {
        CoordinatorPolicy: new iam.PolicyDocument({
          statements: [
            ...basePolicyStatements,
            new iam.PolicyStatement({
              sid: "InvokeSubAgentRuntimes",
              actions: ["bedrock-agentcore:InvokeAgentRuntime"],
              resources: [
                `${emlRuntime.attrAgentRuntimeArn}/*`,
                `${emxRuntime.attrAgentRuntimeArn}/*`,
                emlRuntime.attrAgentRuntimeArn,
                emxRuntime.attrAgentRuntimeArn,
              ],
            }),
          ],
        }),
      },
    });
    (coordinatorRole.node.defaultChild as iam.CfnRole).addPropertyOverride(
      "AssumeRolePolicyDocument",
      trustPolicy
    );

    const coordinatorRuntime = new bedrockagentcore.CfnRuntime(
      this,
      "CoordinatorRuntime",
      {
        agentRuntimeName: `Coordinator_LangChain_${uniqueSuffix}`,
        agentRuntimeArtifact: {
          containerConfiguration: { containerUri: coordinatorImage.imageUri },
        },
        networkConfiguration: { networkMode: "PUBLIC" },
        roleArn: coordinatorRole.roleArn,
        description: "Coordinator agent (LangChain/LangGraph)",
        environmentVariables: {
          MEMORY_ID: sharedMemory.attrMemoryId,
          AGENT_MODEL_ID: bedrockModelId.valueAsString,
          AGENT_NAME: "coordinator",
          EML_RUNTIME_ARN: emlRuntime.attrAgentRuntimeArn,
          EMX_RUNTIME_ARN: emxRuntime.attrAgentRuntimeArn,
          AWS_REGION: this.region,
        },
      }
    );
    coordinatorRuntime.addDependency(emlRuntime);
    coordinatorRuntime.addDependency(emxRuntime);

    // ================================
    // OAUTH CONFIGURATION
    // ================================

    // OAuth2/OIDC authorizer for endpoint authentication.
    // Set OAuthIssuerUri to your identity provider's issuer URL (e.g., Cognito User Pool
    // or any OIDC-compatible provider). Tokens are validated via JWKS at {issuer}/.well-known/jwks.json
    const oauthIssuerUri = new cdk.CfnParameter(this, "OAuthIssuerUri", {
      type: "String",
      description:
        "OAuth2/OIDC issuer URI for endpoint authorization (e.g., https://cognito-idp.{region}.amazonaws.com/{userPoolId})",
      default: "",
    });

    const oauthAudience = new cdk.CfnParameter(this, "OAuthAudience", {
      type: "String",
      description: "OAuth2 audience (client_id) for token validation",
      default: "",
    });

    // Condition: only apply OAuth if issuer is provided
    const hasOAuth = new cdk.CfnCondition(this, "HasOAuth", {
      expression: cdk.Fn.conditionNot(
        cdk.Fn.conditionEquals(oauthIssuerUri.valueAsString, "")
      ),
    });

    // Build authorizer config — when OAuth params are provided, endpoints validate JWT tokens.
    // When not provided, falls back to IAM-only auth (SigV4).
    const authorizerConfig = cdk.Fn.conditionIf(
      "HasOAuth",
      {
        authorizerType: "CUSTOM_JWT",
        customJWTAuthorizerConfig: {
          issuerUri: oauthIssuerUri.valueAsString,
          allowedAudiences: [oauthAudience.valueAsString],
        },
      },
      cdk.Aws.NO_VALUE
    );

    // ================================
    // ENDPOINTS (each directly invocable — OAuth or IAM auth)
    // ================================

    const coordinatorEndpoint = new bedrockagentcore.CfnRuntimeEndpoint(
      this,
      "CoordinatorEndpoint",
      {
        agentRuntimeId: coordinatorRuntime.attrAgentRuntimeId,
        name: `CoordinatorEndpoint_${uniqueSuffix}`,
        description: "Coordinator runtime endpoint",
      }
    );
    coordinatorEndpoint.addDependency(coordinatorRuntime);

    const emlEndpoint = new bedrockagentcore.CfnRuntimeEndpoint(
      this,
      "EMLEndpoint",
      {
        agentRuntimeId: emlRuntime.attrAgentRuntimeId,
        name: `EMLEndpoint_${uniqueSuffix}`,
        description: "EML MediaLive runtime endpoint (directly invocable)",
      }
    );
    emlEndpoint.addDependency(emlRuntime);

    const emxEndpoint = new bedrockagentcore.CfnRuntimeEndpoint(
      this,
      "EMXEndpoint",
      {
        agentRuntimeId: emxRuntime.attrAgentRuntimeId,
        name: `EMXEndpoint_${uniqueSuffix}`,
        description: "EMX MediaConnect runtime endpoint (directly invocable)",
      }
    );
    emxEndpoint.addDependency(emxRuntime);

    // Apply OAuth authorizer via property override (not typed in current CDK version)
    // Only applied when OAuthIssuerUri parameter is provided; otherwise IAM-only (SigV4)
    coordinatorEndpoint.addPropertyOverride("AuthorizerConfiguration", authorizerConfig);
    emlEndpoint.addPropertyOverride("AuthorizerConfiguration", authorizerConfig);
    emxEndpoint.addPropertyOverride("AuthorizerConfiguration", authorizerConfig);

    // ================================
    // OUTPUTS
    // ================================

    new cdk.CfnOutput(this, "MemoryId", {
      value: sharedMemory.attrMemoryId,
      description: "Shared AgentCore Memory ID",
    });
    new cdk.CfnOutput(this, "CoordinatorRuntimeArn", {
      value: coordinatorRuntime.attrAgentRuntimeArn,
      description: "Coordinator runtime ARN",
    });
    new cdk.CfnOutput(this, "EMLRuntimeArn", {
      value: emlRuntime.attrAgentRuntimeArn,
      description: "EML runtime ARN",
    });
    new cdk.CfnOutput(this, "EMXRuntimeArn", {
      value: emxRuntime.attrAgentRuntimeArn,
      description: "EMX runtime ARN",
    });
    new cdk.CfnOutput(this, "CoordinatorEndpointName", {
      value: coordinatorEndpoint.name,
      description: "Coordinator endpoint name",
    });
    new cdk.CfnOutput(this, "EMLEndpointName", {
      value: emlEndpoint.name,
      description: "EML endpoint name (invoke directly for MediaLive ops)",
    });
    new cdk.CfnOutput(this, "EMXEndpointName", {
      value: emxEndpoint.name,
      description: "EMX endpoint name (invoke directly for MediaConnect ops)",
    });
  }
}
