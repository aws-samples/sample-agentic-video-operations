/**
 * The media ops hub on Amazon Bedrock AgentCore (docs/extend_the_hub.md §1).
 *
 * - One runtime runs the Strands hub with the domain packs named by `-c mediaDomains=...`.
 * - IAM is declared by each pack in samples/<key>/iam_permissions.json: every `read`
 *   statement is granted, `write` statements only with `-c allowWrites=true`.
 * - One Secrets Manager secret holds APPROVAL_SIGNING_KEY. Every container reads the same
 *   secret, so an approval paused in one container verifies in another.
 * - HUB_LOCAL_MODE is never set here: a request without an actor is refused.
 */

import * as fs from 'fs';
import * as path from 'path';
import * as cdk from 'aws-cdk-lib';
import { aws_bedrockagentcore as bedrockagentcore } from 'aws-cdk-lib';
import * as ecr_assets from 'aws-cdk-lib/aws-ecr-assets';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { Construct } from 'constructs';

const SAMPLES_DIR = path.join(__dirname, '../../..');
const REPOSITORY_ROOT = path.join(SAMPLES_DIR, '..');
const DEFAULT_MEDIA_DOMAINS = 'medialive,mediaconnect';
// The hub refuses a request without it, so AgentCore must forward it to the container.
export const ACTOR_HEADER = 'X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actor-Id';
// One hub per account and region. scripts/manage_hub_stack.py RUNTIME_NAME must match: its
// destroy deletes only log groups of this exact runtime name.
export const RUNTIME_NAME = 'MediaOpsHubRuntime';

interface PackStatement {
  actions: string[];
  resources: string[];
}

interface PackPermissions {
  read: PackStatement[];
  write: PackStatement[];
}

export class MediaOpsHubStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const mediaDomains = parseMediaDomains(
      this.node.tryGetContext('mediaDomains') ?? DEFAULT_MEDIA_DOMAINS,
    );
    const allowWrites = `${this.node.tryGetContext('allowWrites') ?? 'false'}` === 'true';

    const bedrockModelId = new cdk.CfnParameter(this, 'BedrockModelId', {
      type: 'String',
      description: 'Bedrock model for the hub agent (AGENT_MODEL_ID in the root .env)',
      default: 'us.anthropic.claude-sonnet-4-6',
    });
    const thumbnailModelId = new cdk.CfnParameter(this, 'ThumbnailModelId', {
      type: 'String',
      description: 'Bedrock vision model for thumbnails (THUMBNAIL_MODEL_ID in the root .env)',
      default: 'us.anthropic.claude-haiku-4-5-20251001-v1:0',
    });

    const image = new ecr_assets.DockerImageAsset(this, 'RuntimeDockerImage', {
      directory: REPOSITORY_ROOT,
      file: 'samples/hub/Dockerfile',
      platform: ecr_assets.Platform.LINUX_ARM64,
      exclude: [
        '**/.git', '**/.venv', '**/node_modules', '**/cdk.out', '**/__pycache__',
        '**/.pytest_cache', '.claude', '.kiro', 'docs/images', 'samples/hydrolix',
        'samples/hub/cdk', 'samples/*/tests',
      ],
    });

    const signingKey = new secretsmanager.Secret(this, 'ApprovalSigningKey', {
      description: 'HMAC key the hub signs operator approvals with (APPROVAL_SIGNING_KEY)',
      generateSecretString: { passwordLength: 64, excludePunctuation: true },
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const role = new iam.Role(this, 'AgentCoreExecutionRole', {
      assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com'),
      description: `Media ops hub runtime: ${mediaDomains.join(', ')}`,
    });
    (role.node.defaultChild as iam.CfnRole).addPropertyOverride('AssumeRolePolicyDocument', {
      Version: '2012-10-17',
      Statement: [
        {
          Effect: 'Allow',
          Principal: { Service: 'bedrock-agentcore.amazonaws.com' },
          Action: ['sts:AssumeRole', 'sts:TagSession'],
          Condition: { StringEquals: { 'aws:SourceAccount': this.account } },
        },
      ],
    });
    image.repository.grantPull(role);
    signingKey.grantRead(role);
    for (const domain of mediaDomains) {
      for (const statement of this.packStatements(domain, allowWrites)) {
        role.addToPolicy(statement);
      }
    }

    const suffix = cdk.Names.uniqueId(this).slice(-8).toLowerCase().replace(/[^a-z0-9]/g, '');
    const memory = new bedrockagentcore.CfnMemory(this, 'HubMemory', {
      name: `MediaOpsHubMemory_${suffix}`,
      eventExpiryDuration: 7,
      memoryExecutionRoleArn: role.roleArn,
      description: 'Sessions and paused approvals of the media ops hub',
    });

    const runtime = new bedrockagentcore.CfnRuntime(this, 'HubRuntime', {
      agentRuntimeName: RUNTIME_NAME,
      agentRuntimeArtifact: { containerConfiguration: { containerUri: image.imageUri } },
      networkConfiguration: { networkMode: 'PUBLIC' },
      roleArn: role.roleArn,
      description: 'The media ops hub: one Strands agent over the selected domain packs',
      requestHeaderConfiguration: { requestHeaderAllowlist: [ACTOR_HEADER] },
      environmentVariables: {
        AWS_REGION: this.region,
        AGENT_MODEL_ID: bedrockModelId.valueAsString,
        THUMBNAIL_MODEL_ID: thumbnailModelId.valueAsString,
        MEDIA_DOMAINS: mediaDomains.join(','),
        ALLOW_WRITES: allowWrites ? 'true' : 'false',
        MEMORY_ID: memory.attrMemoryId,
        APPROVAL_SIGNING_KEY_SECRET_ARN: signingKey.secretArn,
      },
    });
    runtime.addDependency(memory);
    for (const statement of this.runtimeStatements(memory.attrMemoryArn)) {
      role.addToPolicy(statement);
    }

    const endpoint = new bedrockagentcore.CfnRuntimeEndpoint(this, 'HubEndpoint', {
      agentRuntimeId: runtime.attrAgentRuntimeId,
      name: `MediaOpsHubEndpoint_${suffix}`,
      description: 'Endpoint for invoking the media ops hub',
    });
    endpoint.addDependency(runtime);

    // Who may invoke: only principals with this policy (or broader IAM). The actor header is
    // caller-supplied, so actor isolation holds only among these principals (extend_the_hub.md §1).
    const invokePolicy = new iam.ManagedPolicy(this, 'InvokeHubPolicy', {
      description: 'Invoke the media ops hub runtime and its endpoint, nothing else',
      statements: [
        new iam.PolicyStatement({
          sid: 'InvokeHub',
          actions: ['bedrock-agentcore:InvokeAgentRuntime'],
          resources: [runtime.attrAgentRuntimeArn, `${runtime.attrAgentRuntimeArn}/runtime-endpoint/*`],
        }),
      ],
    });
    const invokerRoleName = this.node.tryGetContext('invokerRoleName');
    if (invokerRoleName) {
      invokePolicy.attachToRole(iam.Role.fromRoleName(this, 'InvokerRole', `${invokerRoleName}`));
    }

    new cdk.CfnOutput(this, 'InvokePolicyArn', { value: invokePolicy.managedPolicyArn });
    new cdk.CfnOutput(this, 'AgentRuntimeArn', { value: runtime.attrAgentRuntimeArn });
    new cdk.CfnOutput(this, 'AgentRuntimeId', { value: runtime.attrAgentRuntimeId });
    new cdk.CfnOutput(this, 'AgentEndpointName', { value: endpoint.name });
    new cdk.CfnOutput(this, 'MemoryId', { value: memory.attrMemoryId });
    new cdk.CfnOutput(this, 'MediaDomains', { value: mediaDomains.join(',') });
  }

  /** What every hub runtime needs, whatever packs it loads. */
  private runtimeStatements(memoryArn: string): iam.PolicyStatement[] {
    // Only this runtime's own log groups (runtime ids are `<RUNTIME_NAME>-<suffix>`).
    const logGroup = `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/runtimes/${RUNTIME_NAME}-*`;
    return [
      new iam.PolicyStatement({
        sid: 'InvokeAgentModel',
        actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
        resources: [
          'arn:aws:bedrock:*::foundation-model/*',
          `arn:aws:bedrock:${this.region}:${this.account}:inference-profile/*`,
        ],
      }),
      new iam.PolicyStatement({
        sid: 'UseHubMemory',
        actions: [
          'bedrock-agentcore:CreateEvent', 'bedrock-agentcore:GetEvent',
          'bedrock-agentcore:ListEvents', 'bedrock-agentcore:ListSessions',
          'bedrock-agentcore:GetMemory', 'bedrock-agentcore:GetMemoryRecord',
          'bedrock-agentcore:ListMemoryRecords', 'bedrock-agentcore:RetrieveMemoryRecords',
          'bedrock-agentcore:DeleteMemoryRecord',
        ],
        resources: [memoryArn], // this hub's memory only
      }),
      new iam.PolicyStatement({
        sid: 'WriteRuntimeLogs',
        actions: ['logs:CreateLogGroup', 'logs:CreateLogStream', 'logs:PutLogEvents', 'logs:DescribeLogStreams'],
        resources: [logGroup, `${logGroup}:log-stream:*`],
      }),
      new iam.PolicyStatement({
        sid: 'DescribeLogGroups',
        actions: ['logs:DescribeLogGroups'],
        resources: [`arn:aws:logs:${this.region}:${this.account}:log-group:*`],
      }),
      new iam.PolicyStatement({
        sid: 'WriteTraces',
        actions: ['xray:PutTraceSegments', 'xray:PutTelemetryRecords', 'xray:GetSamplingRules', 'xray:GetSamplingTargets'],
        resources: ['*'], // X-Ray has no resource-level permissions
      }),
      new iam.PolicyStatement({
        sid: 'PutRuntimeMetrics',
        actions: ['cloudwatch:PutMetricData'],
        resources: ['*'], // PutMetricData has no resource-level permissions
        conditions: { StringEquals: { 'cloudwatch:namespace': 'bedrock-agentcore' } },
      }),
    ];
  }

  /** The pack's declared IAM: read always, write only when writes are allowed. */
  private packStatements(domain: string, allowWrites: boolean): iam.PolicyStatement[] {
    const permissions = readPackPermissions(domain);
    const groups: [string, PackStatement[]][] = [['Read', permissions.read]];
    if (allowWrites) {
      groups.push(['Write', permissions.write]);
    }
    return groups.flatMap(([kind, statements]) =>
      statements.map(
        (statement, index) =>
          new iam.PolicyStatement({
            sid: `${pascalCase(domain)}${kind}${index}`,
            actions: statement.actions,
            resources: statement.resources.map((resource) =>
              resource.split('{region}').join(this.region).split('{account}').join(this.account),
            ),
          }),
      ),
    );
  }
}

export function parseMediaDomains(value: string): string[] {
  const domains = [...new Set(`${value}`.split(',').map((d) => d.trim()).filter(Boolean))];
  if (domains.length === 0) {
    throw new Error('mediaDomains is empty. Pass -c mediaDomains=medialive (comma-separated).');
  }
  return domains;
}

export function readPackPermissions(domain: string): PackPermissions {
  const file = path.join(SAMPLES_DIR, domain, 'iam_permissions.json');
  if (!/^[a-z0-9-]+$/.test(domain) || !fs.existsSync(file)) {
    throw new Error(`Unknown media domain "${domain}": samples/${domain}/iam_permissions.json not found.`);
  }
  return JSON.parse(fs.readFileSync(file, 'utf8')) as PackPermissions;
}

function pascalCase(value: string): string {
  return value.split(/[^a-z0-9]/i).map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join('');
}
