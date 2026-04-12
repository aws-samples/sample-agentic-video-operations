/**
 * CDK Stack for MediaLive AgentCore Deployment
 *
 * Infrastructure for a MediaLive operations agent powered by Amazon Bedrock AgentCore.
 * Components:
 * - IAM role with least-privilege MediaLive, CloudWatch, Bedrock, and AgentCore permissions
 * - Docker image asset (auto-built ECR)
 * - AgentCore Memory for conversation context
 * - AgentCore Runtime (ARM64 container)
 * - AgentCore Runtime Endpoint
 */

import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as ecr_assets from 'aws-cdk-lib/aws-ecr-assets';
import * as path from 'path';
import { aws_bedrockagentcore as bedrockagentcore } from 'aws-cdk-lib';

export class MediaLiveAgentCoreStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ================================
    // STACK PARAMETERS
    // ================================

    const bedrockModelId = new cdk.CfnParameter(this, 'BedrockModelId', {
      type: 'String',
      description: 'Bedrock model ID for the MediaLive agent LLM',
      default: 'us.anthropic.claude-sonnet-4-6',
    });

    const thumbnailModelId = new cdk.CfnParameter(this, 'ThumbnailModelId', {
      type: 'String',
      description: 'Bedrock model ID for thumbnail visual analysis',
      default: 'us.anthropic.claude-haiku-4-5-20251001-v1:0',
    });

    const defaultChannelId = new cdk.CfnParameter(this, 'DefaultChannelId', {
      type: 'String',
      description: 'MediaLive channel ID (required — no default)',
    });

    // ================================
    // DOCKER IMAGE ASSET
    // ================================

    const dockerImageAsset = new ecr_assets.DockerImageAsset(this, 'RuntimeDockerImage', {
      directory: path.join(__dirname, '../../'),
      platform: ecr_assets.Platform.LINUX_ARM64,
    });

    // ================================
    // IAM EXECUTION ROLE
    // ================================

    const agentCoreRole = new iam.Role(this, 'AgentCoreExecutionRole', {
      roleName: `AgentCoreExecution-medialive-${this.region}`,
      assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com'),
      inlinePolicies: {
        AgentCoreExecutionPolicy: new iam.PolicyDocument({
          statements: [
            // ECR image access
            new iam.PolicyStatement({
              sid: 'ECRImageAccess',
              effect: iam.Effect.ALLOW,
              actions: [
                'ecr:BatchCheckLayerAvailability',
                'ecr:BatchGetImage',
                'ecr:GetDownloadUrlForLayer',
                'ecr:PutImage',
                'ecr:InitiateLayerUpload',
                'ecr:UploadLayerPart',
                'ecr:CompleteLayerUpload',
              ],
              resources: [`arn:aws:ecr:${this.region}:${this.account}:repository/*`],
            }),
            // ECR authorization token
            new iam.PolicyStatement({
              sid: 'ECRTokenAccess',
              effect: iam.Effect.ALLOW,
              actions: ['ecr:GetAuthorizationToken'],
              resources: ['*'],
            }),
            // MediaLive read and control operations
            new iam.PolicyStatement({
              sid: 'MediaLiveAccess',
              effect: iam.Effect.ALLOW,
              actions: [
                'medialive:ListChannels',
                'medialive:DescribeChannel',
                'medialive:StartChannel',
                'medialive:StopChannel',
                'medialive:DescribeThumbnails',
                'medialive:DescribeSchedule',
                'medialive:BatchUpdateSchedule',
                'medialive:DeleteSchedule',
                'medialive:ListInputs',
                'medialive:DescribeInput',
              ],
              resources: ['*'],
            }),
            // CloudWatch metrics
            new iam.PolicyStatement({
              sid: 'CloudWatchMetrics',
              effect: iam.Effect.ALLOW,
              actions: ['cloudwatch:GetMetricStatistics'],
              resources: ['*'],
            }),
            // CloudWatch Logs — filter events
            new iam.PolicyStatement({
              sid: 'CloudWatchLogs',
              effect: iam.Effect.ALLOW,
              actions: ['logs:FilterLogEvents'],
              resources: ['*'],
            }),
            // Bedrock model invocation
            new iam.PolicyStatement({
              sid: 'BedrockModelInvocation',
              effect: iam.Effect.ALLOW,
              actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
              resources: [
                'arn:aws:bedrock:*::foundation-model/*',
                `arn:aws:bedrock:${this.region}:${this.account}:*`,
              ],
            }),
            // AgentCore Memory CRUD
            new iam.PolicyStatement({
              sid: 'BedrockAgentCoreMemoryAccess',
              effect: iam.Effect.ALLOW,
              actions: [
                'bedrock-agentcore:GetMemoryRecord',
                'bedrock-agentcore:GetMemory',
                'bedrock-agentcore:RetrieveMemoryRecords',
                'bedrock-agentcore:DeleteMemoryRecord',
                'bedrock-agentcore:ListMemoryRecords',
                'bedrock-agentcore:CreateEvent',
                'bedrock-agentcore:ListSessions',
                'bedrock-agentcore:ListEvents',
                'bedrock-agentcore:GetEvent',
              ],
              resources: ['*'],
            }),
            // CloudWatch observability (conditioned on namespace)
            new iam.PolicyStatement({
              sid: 'CloudWatchObservability',
              effect: iam.Effect.ALLOW,
              actions: ['cloudwatch:PutMetricData'],
              resources: ['*'],
              conditions: {
                StringEquals: { 'cloudwatch:namespace': 'bedrock-agentcore' },
              },
            }),
            // X-Ray tracing
            new iam.PolicyStatement({
              sid: 'XRayTracing',
              effect: iam.Effect.ALLOW,
              actions: [
                'xray:PutTraceSegments',
                'xray:PutTelemetryRecords',
                'xray:GetSamplingRules',
                'xray:GetSamplingTargets',
              ],
              resources: ['*'],
            }),
            // CloudWatch Logs management — scoped to AgentCore runtime logs
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: ['logs:DescribeLogStreams', 'logs:CreateLogGroup'],
              resources: [
                `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/runtimes/*`,
              ],
            }),
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: ['logs:DescribeLogGroups'],
              resources: [`arn:aws:logs:${this.region}:${this.account}:log-group:*`],
            }),
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: ['logs:CreateLogStream', 'logs:PutLogEvents'],
              resources: [
                `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*`,
              ],
            }),
            // AgentCore workload identity
            new iam.PolicyStatement({
              sid: 'GetAgentAccessToken',
              effect: iam.Effect.ALLOW,
              actions: [
                'bedrock-agentcore:GetWorkloadAccessToken',
                'bedrock-agentcore:GetWorkloadAccessTokenForJWT',
                'bedrock-agentcore:GetWorkloadAccessTokenForUserId',
              ],
              resources: [
                `arn:aws:bedrock-agentcore:${this.region}:${this.account}:workload-identity-directory/default`,
                `arn:aws:bedrock-agentcore:${this.region}:${this.account}:workload-identity-directory/default/workload-identity/*`,
              ],
            }),
            // Bedrock model invocation for memory operations
            new iam.PolicyStatement({
              sid: 'BedrockModelInvocationMemory',
              effect: iam.Effect.ALLOW,
              actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
              resources: [
                'arn:aws:bedrock:*::foundation-model/*',
                'arn:aws:bedrock:*:*:inference-profile/*',
              ],
            }),
          ],
        }),
      },
    });

    // Override trust policy to include sts:TagSession
    (agentCoreRole.node.defaultChild as iam.CfnRole).addPropertyOverride(
      'AssumeRolePolicyDocument',
      {
        Version: '2012-10-17',
        Statement: [
          {
            Sid: 'Statement1',
            Effect: 'Allow',
            Principal: { Service: 'bedrock-agentcore.amazonaws.com' },
            Action: ['sts:AssumeRole', 'sts:TagSession'],
          },
        ],
      },
    );

    // ================================
    // AGENTCORE MEMORY
    // ================================

    const uniqueSuffix = cdk.Names.uniqueId(this).slice(-8).toLowerCase().replace(/[^a-z0-9]/g, '');

    const agentMemory = new bedrockagentcore.CfnMemory(this, 'AgentMemory', {
      name: `MediaLiveAgentMemory_${uniqueSuffix}`,
      eventExpiryDuration: 7,
      memoryExecutionRoleArn: agentCoreRole.roleArn,
      description: 'Short-term memory for MediaLive agent conversations',
    });

    // ================================
    // AGENTCORE RUNTIME
    // ================================

    const agentRuntime = new bedrockagentcore.CfnRuntime(this, 'AgentRuntime', {
      agentRuntimeName: `MediaLiveRuntime_${uniqueSuffix}`,
      agentRuntimeArtifact: {
        containerConfiguration: {
          containerUri: dockerImageAsset.imageUri,
        },
      },
      networkConfiguration: {
        networkMode: 'PUBLIC',
      },
      roleArn: agentCoreRole.roleArn,
      description: 'Container runtime for MediaLive operations agent',
      environmentVariables: {
        AGENT_MODEL_ID: bedrockModelId.valueAsString,
        THUMBNAIL_MODEL_ID: thumbnailModelId.valueAsString,
        MEDIALIVE_DEFAULT_CHANNEL_ID: defaultChannelId.valueAsString,
        MEMORY_ID: agentMemory.attrMemoryId,
        AWS_REGION: this.region,
      },
    });

    agentRuntime.addDependency(agentMemory);

    // ================================
    // AGENTCORE RUNTIME ENDPOINT
    // ================================

    const runtimeEndpoint = new bedrockagentcore.CfnRuntimeEndpoint(this, 'RuntimeEndpoint', {
      agentRuntimeId: agentRuntime.attrAgentRuntimeId,
      name: `MediaLiveEndpoint_${uniqueSuffix}`,
      description: 'Endpoint for invoking the MediaLive operations agent',
    });

    runtimeEndpoint.addDependency(agentRuntime);

    // ================================
    // CLOUDFORMATION OUTPUTS
    // ================================

    new cdk.CfnOutput(this, 'MemoryId', {
      value: agentMemory.attrMemoryId,
      description: 'The ID of the AgentCore Memory',
    });

    new cdk.CfnOutput(this, 'AgentRuntimeArn', {
      value: agentRuntime.attrAgentRuntimeArn,
      description: 'The ARN of the AgentCore runtime',
    });

    new cdk.CfnOutput(this, 'AgentEndpointName', {
      value: runtimeEndpoint.name,
      description: 'The name of the AgentCore runtime endpoint',
    });
  }
}
