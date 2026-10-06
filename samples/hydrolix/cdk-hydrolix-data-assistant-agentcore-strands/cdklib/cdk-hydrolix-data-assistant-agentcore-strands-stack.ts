/**
 * CDK Stack for AgentCore Strands Hydrolix Data Assistant
 * 
 * Infrastructure for a Hydrolix data analyst assistant powered by Amazon Bedrock AgentCore.
 * Components:
 * - DynamoDB tables for query results
 * - IAM roles and permissions for AgentCore
 * - Hydrolix credentials in Secrets Manager
 *
 * Inbound auth (RB9): with -c jwtDiscoveryUrl=... -c jwtClientIds=... the runtime accepts
 * only Cognito access tokens from that user pool and app clients, forwards only the
 * Authorization header, and the agent's actor is the token's `sub`. Without them the
 * runtime is IAM-authorized and the agent runs with memory off (no verified identity).
 */

import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as iam from "aws-cdk-lib/aws-iam";
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as ecr_assets from 'aws-cdk-lib/aws-ecr-assets';
import * as fs from 'fs';
import * as path from 'path';
import { aws_bedrockagentcore as bedrockagentcore } from 'aws-cdk-lib';

// AgentCore verifies this header's token and forwards it; the agent reads `sub` from it.
export const AUTHORIZATION_HEADER = 'Authorization';
const DISCOVERY_SUFFIX = '/.well-known/openid-configuration';

export interface JwtSettings {
  discoveryUrl: string;
  issuer: string;
  clientIds: string[];
}

/** Both or neither: a discovery URL without client ids would admit any client of the pool. */
export function readJwtSettings(discoveryUrl?: string, clientIds?: string): JwtSettings | undefined {
  const url = `${discoveryUrl ?? ''}`.trim();
  const clients = `${clientIds ?? ''}`.split(',').map((c) => c.trim()).filter(Boolean);
  if (!url && clients.length === 0) {
    return undefined;
  }
  if (!/^https:\/\/\S+\/\.well-known\/openid-configuration$/.test(url) || clients.length === 0) {
    throw new Error(
      'JWT auth needs both -c jwtDiscoveryUrl=https://<issuer>/.well-known/openid-configuration '
      + 'and -c jwtClientIds=<app client id>[,<app client id>].',
    );
  }
  // OpenID Connect discovery: the issuer is the discovery URL without the well-known suffix.
  return { discoveryUrl: url, issuer: url.slice(0, -DISCOVERY_SUFFIX.length), clientIds: clients };
}

export class CdkHydrolixDataAssistantAgentcoreStrandsStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ================================
    // STACK PARAMETERS
    // ================================

    // Bedrock model ID for the agent
    // The default comes from `-c agentModelId`, which the deploy script passes to the security
    // diff and the deploy alike (cdk diff takes no --parameters), so the two synthesize the same
    // template. The deploy then uses this default (--no-previous-parameters).
    const agentModelId = `${this.node.tryGetContext("agentModelId") ?? ""}`.trim() || "us.anthropic.claude-sonnet-4-6";
    if (!new RegExp(MODEL_ID_PATTERN).test(agentModelId)) {
      throw new Error(`agentModelId must be a Bedrock model or cross-Region profile id; got '${agentModelId}'.`);
    }
    const bedrockModelId = new cdk.CfnParameter(this, "BedrockModelId", {
      type: "String",
      description: "The Bedrock model or cross-Region inference-profile id for the agent (AGENT_MODEL_ID)",
      default: agentModelId,
      // An optional profile prefix, then exactly provider.model: no '*', '/' or ARN can widen
      // the grant, and the base model below can be read off the id's dot-separated parts.
      allowedPattern: MODEL_ID_PATTERN,
      constraintDescription: "a Bedrock model id (provider.model) or a cross-Region profile id (us.provider.model)",
    });
    const bedrockModelGrant = invokeModelResources(this, bedrockModelId);

    // Hydrolix table name for time-series data queries
    const hydrolixTable = new cdk.CfnParameter(this, "HydrolixTable", {
      type: "String",
      description: "The Hydrolix table name (format: database.table)",
      default: "database.table",
      // The only table the model may read, so the same rule as the runtime's HYDROLIX_TABLE
      // setting: database.table, neither part starting with "_", and never a metadata
      // database (system, information_schema, in any case). Character classes, not an
      // inline (?i), so CloudFormation's Java regex and the jest test's JavaScript agree.
      allowedPattern:
        "^(?!(?:[Ss][Yy][Ss][Tt][Ee][Mm]|[Ii][Nn][Ff][Oo][Rr][Mm][Aa][Tt][Ii][Oo][Nn]_[Ss][Cc][Hh][Ee][Mm][Aa])\\.)" +
        "[A-Za-z0-9-][A-Za-z0-9_-]*\\.[A-Za-z0-9-][A-Za-z0-9_-]*$",
      constraintDescription:
        "database.table: letters, digits, _ or -, neither part starting with _, not in system or information_schema",
    });
    const jwt = readJwtSettings(
      this.node.tryGetContext('jwtDiscoveryUrl'),
      this.node.tryGetContext('jwtClientIds'),
    );
    const uniqueSuffix = cdk.Names.uniqueId(this).slice(-8).toLowerCase().replace(/[^a-z0-9]/g, '');
    const runtimeName = `HydrolixRuntime_${uniqueSuffix}`;

    // ================================
    // DYNAMODB TABLES
    // ================================

    // The SQL each request ran, per verified user (T41): the partition key is the caller's
    // token `sub`, the sort key a millisecond timestamp with a unique suffix. Only the
    // runtime writes it; the web app gets its own records in the response stream.
    const rawQueryResults = new dynamodb.Table(this, "QueryRecords", {
      partitionKey: {
        name: "actor_id",
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: "recorded_at",
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
      removalPolicy: cdk.RemovalPolicy.DESTROY
    });

    // The results table of earlier versions, keyed by the client's prompt_uuid. Upgrading
    // must not delete it: CloudFormation applies the *deployed* template's DeletionPolicy to
    // a resource a template drops, and that was Delete. So this release keeps it exactly as
    // it was (same construct id and properties, so no replacement) with RETAIN and no
    // grants; a later release can drop it and CloudFormation will leave it in the account.
    // Delete it by hand (README, Teardown) once its history isn't needed.
    const retiredQueryResults = new dynamodb.Table(this, "RawQueryResults", {
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
      removalPolicy: cdk.RemovalPolicy.RETAIN
    });

    // ================================
    // SECRETS MANAGER
    // ================================

    // Hydrolix credentials stored in AWS Secrets Manager with default placeholder values
    const hydrolixSecret = new secretsmanager.Secret(this, "HydrolixSecret", {
      description: "Hydrolix connection credentials for time-series data analysis",
      removalPolicy: cdk.RemovalPolicy.DESTROY,
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
              effect: iam.Effect.ALLOW,
              actions: [
                'logs:DescribeLogStreams',
                'logs:CreateLogGroup'
              ],
              resources: [
                `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/runtimes/${runtimeName}-*`
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
                `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/runtimes/${runtimeName}-*:log-stream:*`
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
              sid: 'BedrockModelInvocation',
              effect: iam.Effect.ALLOW,
              actions: [
                'bedrock:InvokeModel',
                'bedrock:InvokeModelWithResponseStream'
              ],
              resources: bedrockModelGrant,
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
            // The runtime only records queries; nothing reads the table back through it.
            new iam.PolicyStatement({
              sid: 'DynamoDBTableAccess',
              effect: iam.Effect.ALLOW,
              actions: ['dynamodb:PutItem'],
              resources: [
                rawQueryResults.tableArn
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
    dockerImageAsset.repository.grantPull(agentCoreRole);

    // ================================
    // BEDROCK AGENTCORE MEMORY
    // ================================

    // Short-term memory for AgentCore to maintain conversation context
    const agentMemory = new bedrockagentcore.CfnMemory(this, 'AgentMemory', {
      name: `HydrolixAssistantMemory_${uniqueSuffix}`,
      eventExpiryDuration: 7, // Events expire after 7 days
      memoryExecutionRoleArn: agentCoreRole.roleArn,
      description: 'Short-term memory for Hydrolix data analyst assistant conversations',
    });
    const memoryPolicy = new iam.Policy(this, 'AgentMemoryPolicy', {
      statements: [
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
          resources: [agentMemory.attrMemoryArn]
        }),
      ],
    });
    memoryPolicy.attachToRole(agentCoreRole);

    // ================================
    // BEDROCK AGENTCORE RUNTIME
    // ================================

    // AgentCore Runtime with container type for the Hydrolix data analyst assistant
    const agentRuntime = new bedrockagentcore.CfnRuntime(this, 'AgentRuntime', {
      agentRuntimeName: runtimeName,
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
      // JWT mode forwards only the verified token; IAM mode forwards no caller header at all.
      requestHeaderConfiguration: jwt ? { requestHeaderAllowlist: [AUTHORIZATION_HEADER] } : undefined,
      authorizerConfiguration: jwt
        ? { customJwtAuthorizer: { discoveryUrl: jwt.discoveryUrl, allowedClients: jwt.clientIds } }
        : undefined,
      environmentVariables: {
        MEMORY_ID: agentMemory.attrMemoryId,
        AGENT_MODEL_ID: bedrockModelId.valueAsString,
        HYDROLIX_SECRET_ARN: hydrolixSecret.secretArn,
        HYDROLIX_TABLE: hydrolixTable.valueAsString,
        QUESTION_ANSWERS_TABLE: rawQueryResults.tableName,
        ...(jwt
          ? { HYDROLIX_JWT_ISSUER: jwt.issuer, HYDROLIX_JWT_ALLOWED_CLIENTS: jwt.clientIds.join(',') }
          : {}),
      },
    });
    
    agentRuntime.node.addDependency(memoryPolicy);
    // grantPull puts the ECR pull in the role's DefaultPolicy, which AgentCore needs when it
    // creates the runtime; RoleArn alone doesn't order the two (RB14).
    agentRuntime.node.addDependency(agentCoreRole.node.findChild('DefaultPolicy'));

    // ================================
    // BEDROCK AGENTCORE RUNTIME ENDPOINT
    // ================================

    // Runtime endpoint for invoking the Hydrolix data analyst assistant
    const runtimeEndpoint = new bedrockagentcore.CfnRuntimeEndpoint(this, 'RuntimeEndpoint', {
      agentRuntimeId: agentRuntime.attrAgentRuntimeId,
      name: `HydrolixEndpoint_${uniqueSuffix}`,
      description: 'Endpoint for invoking the Hydrolix CDN analytics data analyst assistant',
    });


    // ================================
    // CLOUDFORMATION OUTPUTS
    // ================================

    new cdk.CfnOutput(this, "RetiredQueryResultsTableName", {
      value: retiredQueryResults.tableName,
      description: "The results table of earlier versions, retained (not deleted) by upgrade and destroy",
    });

    new cdk.CfnOutput(this, "QuestionAnswersTableName", {
      value: rawQueryResults.tableName,
      description: "The DynamoDB table of executed SQL, per verified user (written by the runtime only)",
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

    new cdk.CfnOutput(this, "InboundAuth", {
      value: jwt ? "jwt" : "iam",
      description: "jwt: Cognito access tokens, actor = token sub; iam: IAM callers, memory off",
    });

    new cdk.CfnOutput(this, "HydrolixTableName", {
      value: hydrolixTable.valueAsString,
      description: "The Hydrolix table name used for time-series queries (format: database.table)",
    });

  }
}

// The repository's one model-id rule (T72), shared with the deploy scripts and the agentic-iops-streaming stack.
// A profile id is <prefix>.<provider>.<model> and routes to the foundation model
// <provider>.<model> in each Region of its geography; a bare id can't start with a prefix.
// The pattern's lookahead works the same in CloudFormation's Java regex and in JavaScript.
const MODEL_ID_RULE = JSON.parse(
  fs.readFileSync(path.join(__dirname, "..", "..", "..", "..", "scripts", "model_id_rule.json"), "utf8"),
) as { profile_prefixes: string[]; pattern: string };
const PROFILE_PREFIXES = MODEL_ID_RULE.profile_prefixes;
export const MODEL_ID_PATTERN = MODEL_ID_RULE.pattern;

/**
 * What invoking the configured model needs (T71, agentic-iops-streaming's T60 rule): for a profile id, the
 * profile in this account and Region plus the foundation model behind it in any Region; for
 * a bare model id, that foundation model only. The base model is derived here, in the
 * template, from the one parameter, so it can never name another model.
 */
export function invokeModelResources(stack: cdk.Stack, modelId: cdk.CfnParameter): string[] {
  const parts = cdk.Fn.split(".", modelId.valueAsString);
  const isProfile = new cdk.CfnCondition(stack, "BedrockModelIdIsInferenceProfile", {
    expression: cdk.Fn.conditionOr(
      ...PROFILE_PREFIXES.map((prefix) => cdk.Fn.conditionEquals(cdk.Fn.select(0, parts), prefix)),
    ),
  });
  const profile = `arn:aws:bedrock:${stack.region}:${stack.account}:inference-profile/${modelId.valueAsString}`;
  // Only evaluated for a profile id, which the pattern guarantees has three parts.
  const baseOfProfile = cdk.Fn.join(".", [cdk.Fn.select(1, parts), cdk.Fn.select(2, parts)]);
  return cdk.Token.asList(cdk.Fn.conditionIf(
    isProfile.logicalId,
    [profile, `arn:aws:bedrock:*::foundation-model/${baseOfProfile}`],
    [`arn:aws:bedrock:*::foundation-model/${modelId.valueAsString}`],
  ));
}
