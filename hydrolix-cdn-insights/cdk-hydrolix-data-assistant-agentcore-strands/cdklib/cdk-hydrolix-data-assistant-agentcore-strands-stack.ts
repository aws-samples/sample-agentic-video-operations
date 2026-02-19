/**
 * CDK Stack for AgentCore Strands Hydrolix Data Assistant
 * 
 * Infrastructure for a Hydrolix data analyst assistant powered by Amazon Bedrock AgentCore.
 * Components:
 * - DynamoDB tables for query results
 * - IAM roles and permissions for AgentCore
 * - Hydrolix credentials in Secrets Manager
 */

import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as iam from "aws-cdk-lib/aws-iam";
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as ecr_assets from 'aws-cdk-lib/aws-ecr-assets';
import * as path from 'path';
import { aws_bedrockagentcore as bedrockagentcore } from 'aws-cdk-lib';

export class CdkHydrolixDataAssistantAgentcoreStrandsStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ================================
    // STACK PARAMETERS
    // ================================

    // Bedrock model ID for the agent
    const bedrockModelId = new cdk.CfnParameter(this, "BedrockModelId", {
      type: "String",
      description: "The Bedrock model ID for the agent",
      default: "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    });

    // Hydrolix table name for time-series data queries
    const hydrolixTable = new cdk.CfnParameter(this, "HydrolixTable", {
      type: "String",
      description: "The Hydrolix table name (format: database.table)",
      default: "database.table",
    });

    // ================================
    // DYNAMODB TABLES
    // ================================

    // DynamoDB table containing SQL query results from the agent
    const rawQueryResults = new dynamodb.Table(this, "RawQueryResults", {
      partitionKey: {
        name: "id",
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: "my_timestamp",
        type: dynamodb.AttributeType.NUMBER,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
      removalPolicy: cdk.RemovalPolicy.DESTROY
    });

    // ================================
    // SECRETS MANAGER
    // ================================

    // Hydrolix credentials stored in AWS Secrets Manager with default placeholder values
    const hydrolixSecret = new secretsmanager.Secret(this, "HydrolixSecret", {
      secretName: `hydrolix-data-assistant-secret`,
      description: "Hydrolix connection credentials for time-series data analysis",
      secretObjectValue: {
        HYDROLIX_HOST: cdk.SecretValue.unsafePlainText("your-hydrolix-host.example.com"),
        HYDROLIX_PORT: cdk.SecretValue.unsafePlainText("8088"),
        HYDROLIX_USER: cdk.SecretValue.unsafePlainText("your-username"),
        HYDROLIX_PASSWORD: cdk.SecretValue.unsafePlainText("your-password"),
      },
    });

    // ================================
    // AGENTCORE IAM ROLE & PERMISSIONS
    // ================================

    // IAM role with comprehensive permissions for Amazon Bedrock AgentCore
    const agentCoreRole = new iam.Role(this, 'AgentCoreMyRole', {
      roleName: `AgentCoreExecution-hydrolix-assistant-${this.region}`,
      assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com'),
      inlinePolicies: {
        'AgentCoreExecutionPolicy': new iam.PolicyDocument({
          statements: [
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
              resources: [
                `arn:aws:ecr:${this.region}:${this.account}:repository/*`
              ]
            }),
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: [
                'logs:DescribeLogStreams',
                'logs:CreateLogGroup'
              ],
              resources: [
                `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/runtimes/*`
              ]
            }),
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: [
                'logs:DescribeLogGroups'
              ],
              resources: [
                `arn:aws:logs:${this.region}:${this.account}:log-group:*`
              ]
            }),
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: [
                'logs:CreateLogStream',
                'logs:PutLogEvents'
              ],
              resources: [
                `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*`
              ]
            }),
            new iam.PolicyStatement({
              sid: 'ECRTokenAccess',
              effect: iam.Effect.ALLOW,
              actions: [
                'ecr:GetAuthorizationToken'
              ],
              resources: ['*']
            }),
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: [
                'xray:PutTraceSegments',
                'xray:PutTelemetryRecords',
                'xray:GetSamplingRules',
                'xray:GetSamplingTargets'
              ],
              resources: ['*']
            }),
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: ['cloudwatch:PutMetricData'],
              resources: ['*'],
              conditions: {
                StringEquals: {
                  'cloudwatch:namespace': 'bedrock-agentcore'
                }
              }
            }),
            new iam.PolicyStatement({
              sid: 'GetAgentAccessToken',
              effect: iam.Effect.ALLOW,
              actions: [
                'bedrock-agentcore:GetWorkloadAccessToken',
                'bedrock-agentcore:GetWorkloadAccessTokenForJWT',
                'bedrock-agentcore:GetWorkloadAccessTokenForUserId'
              ],
              resources: [
                `arn:aws:bedrock-agentcore:${this.region}:${this.account}:workload-identity-directory/default`,
                `arn:aws:bedrock-agentcore:${this.region}:${this.account}:workload-identity-directory/default/workload-identity/*`
              ]
            }),
            new iam.PolicyStatement({
              sid: 'BedrockModelInvocation',
              effect: iam.Effect.ALLOW,
              actions: [
                'bedrock:InvokeModel',
                'bedrock:InvokeModelWithResponseStream'
              ],
              resources: [
                'arn:aws:bedrock:*::foundation-model/*',
                `arn:aws:bedrock:${this.region}:${this.account}:*`
              ]
            }),
            // Permissions for Secrets Manager
            new iam.PolicyStatement({
              sid: 'SecretsManagerAccess',
              effect: iam.Effect.ALLOW,
              actions: [
                'secretsmanager:GetSecretValue'
              ],
              resources: [
                hydrolixSecret.secretArn
              ]
            }),
            // Permissions for DynamoDB
            new iam.PolicyStatement({
              sid: 'DynamoDBTableAccess',
              effect: iam.Effect.ALLOW,
              actions: [
                'dynamodb:Query',
                'dynamodb:Scan',
                'dynamodb:GetItem',
                'dynamodb:PutItem',
                'dynamodb:UpdateItem'
              ],
              resources: [
                rawQueryResults.tableArn
              ]
            }),
            // Permissions for AgentCore Memory
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
                'bedrock-agentcore:GetEvent'
              ],
              resources: [
                `*`
              ]
            }),
            new iam.PolicyStatement({
              sid: 'BedrockModelInvocationMemory',
              effect: iam.Effect.ALLOW,
              actions: [
                'bedrock:InvokeModel',
                'bedrock:InvokeModelWithResponseStream'
              ],
              resources: [
                'arn:aws:bedrock:*::foundation-model/*',
                'arn:aws:bedrock:*:*:inference-profile/*'
              ]
            }),
          ]
        })
      }
    });

    // Add the specific trust relationship with sts:TagSession permission
    (agentCoreRole.node.defaultChild as iam.CfnRole).addPropertyOverride(
      'AssumeRolePolicyDocument',
      {
        Version: '2012-10-17',
        Statement: [
          {
            Sid: 'Statement1',
            Effect: 'Allow',
            Principal: {
              Service: 'bedrock-agentcore.amazonaws.com'
            },
            Action: [
              'sts:AssumeRole',
              'sts:TagSession'
            ]
          }
        ]
      }
    );

    // ================================
    // DOCKER IMAGE ASSET
    // ================================

    // Build and push Docker image automatically during CDK deployment
    // DockerImageAsset creates and manages its own ECR repository
    const dockerImageAsset = new ecr_assets.DockerImageAsset(this, 'RuntimeDockerImage', {
      directory: path.join(__dirname, '../hydrolix-data-assistant-agentcore-strands'),
      platform: ecr_assets.Platform.LINUX_ARM64
    });

    // ================================
    // BEDROCK AGENTCORE MEMORY
    // ================================

    // Short-term memory for AgentCore to maintain conversation context
    const uniqueSuffix = cdk.Names.uniqueId(this).slice(-8).toLowerCase().replace(/[^a-z0-9]/g, '');
    const agentMemory = new bedrockagentcore.CfnMemory(this, 'AgentMemory', {
      name: `HydrolixAssistantMemory_${uniqueSuffix}`,
      eventExpiryDuration: 7, // Events expire after 7 days
      memoryExecutionRoleArn: agentCoreRole.roleArn,
      description: 'Short-term memory for Hydrolix data analyst assistant conversations',
    });

    // ================================
    // BEDROCK AGENTCORE RUNTIME
    // ================================

    // AgentCore Runtime with container type for the Hydrolix data analyst assistant
    const agentRuntime = new bedrockagentcore.CfnRuntime(this, 'AgentRuntime', {
      agentRuntimeName: `HydrolixRuntime_${uniqueSuffix}`,
      agentRuntimeArtifact: {
        containerConfiguration: {
          containerUri: dockerImageAsset.imageUri,
        },
      },
      networkConfiguration: {
        networkMode: 'PUBLIC',
      },
      roleArn: agentCoreRole.roleArn,
      description: 'Container runtime for Hydrolix CDN analytics data analyst assistant',
      environmentVariables: {
        MEMORY_ID: agentMemory.attrMemoryId,
        BEDROCK_MODEL_ID: bedrockModelId.valueAsString,
        HYDROLIX_SECRET_ARN: hydrolixSecret.secretArn,
        HYDROLIX_TABLE: hydrolixTable.valueAsString,
        QUESTION_ANSWERS_TABLE: rawQueryResults.tableName,
      },
    });
    
    agentRuntime.addDependency(agentMemory);

    // ================================
    // BEDROCK AGENTCORE RUNTIME ENDPOINT
    // ================================

    // Runtime endpoint for invoking the Hydrolix data analyst assistant
    const runtimeEndpoint = new bedrockagentcore.CfnRuntimeEndpoint(this, 'RuntimeEndpoint', {
      agentRuntimeId: agentRuntime.attrAgentRuntimeId,
      name: `HydrolixEndpoint_${uniqueSuffix}`,
      description: 'Endpoint for invoking the Hydrolix CDN analytics data analyst assistant',
    });

    // Endpoint depends on runtime being created first
    runtimeEndpoint.addDependency(agentRuntime);

    // ================================
    // CLOUDFORMATION OUTPUTS
    // ================================

    new cdk.CfnOutput(this, "QuestionAnswersTableName", {
      value: rawQueryResults.tableName,
      description: "The name of the DynamoDB table for storing query results",
    });

    new cdk.CfnOutput(this, "QuestionAnswersTableArn", {
      value: rawQueryResults.tableArn,
      description: "The ARN of the DynamoDB table for storing query results",
    });

    new cdk.CfnOutput(this, "AgentRuntimeArn", {
      value: agentRuntime.attrAgentRuntimeArn,
      description: "The ARN of the AgentCore runtime",
    });

    new cdk.CfnOutput(this, "AgentEndpointName", {
      value: runtimeEndpoint.name,
      description: "The name of the AgentCore runtime endpoint",
    });

    new cdk.CfnOutput(this, "MemoryId", {
      value: agentMemory.attrMemoryId,
      description: "The ID of the AgentCore Memory",
    });

    new cdk.CfnOutput(this, "HydrolixSecretArn", {
      value: hydrolixSecret.secretArn,
      description: "The ARN of the Hydrolix credentials secret (update values in Secrets Manager)",
    });

    new cdk.CfnOutput(this, "HydrolixTableName", {
      value: hydrolixTable.valueAsString,
      description: "The Hydrolix table name used for time-series queries (format: database.table)",
    });

  }
}
