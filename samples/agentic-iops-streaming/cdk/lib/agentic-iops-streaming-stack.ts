/**
 * agentic-iops-streaming on Amazon Bedrock AgentCore (docs/extend_agentic_iops_streaming.md §1).
 *
 * - One runtime runs the Strands agent with the domain packs named by `-c mediaDomains=...`.
 * - IAM is declared by each pack in samples/<key>/iam_permissions.json: every `read`
 *   statement is granted, `write` statements only with `-c allowWrites=true`.
 *   `-c writeTag=Key=Value` can limit those writes to tagged channels and flows.
 * - One Secrets Manager secret holds APPROVAL_SIGNING_KEY. Every container reads the same
 *   secret, so an approval paused in one container verifies in another.
 * - AGENTIC_IOPS_LOCAL_MODE is never set here: a request without an actor is refused.
 * - Inbound auth is IAM by default (the actor header names the actor). With
 *   `-c jwtDiscoveryUrl=... -c jwtClientIds=...` the runtime accepts only bearer tokens from
 *   that identity provider, and the actor is the token's `sub` (extend_agentic_iops_streaming.md §1).
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
// The runtime refuses a request without it, so AgentCore must forward it to the container.
export const ACTOR_HEADER = 'X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actor-Id';
// With JWT auth, AgentCore verifies this header's token and forwards it; the runtime reads `sub`.
export const AUTHORIZATION_HEADER = 'Authorization';
const DISCOVERY_SUFFIX = '/.well-known/openid-configuration';
// One agentic-iops-streaming deployment per account and region. scripts/manage_agentic_iops_streaming_stack.py RUNTIME_NAME must match: its
// destroy deletes only log groups of this exact runtime name.
export const RUNTIME_NAME = 'AgenticIopsStreamingRuntime';
// The memory and endpoint name suffix: fixed, never derived from the stack name, so renaming
// the stack (as REN1 did) can't rename these resources again.
export const RESOURCE_NAME_SUFFIX = 'default';

interface PackStatement {
  actions: string[];
  resources: string[];
}

interface PackPermissions {
  read: PackStatement[];
  write: PackStatement[];
}

export interface WriteTag {
  key: string;
  value: string;
}

export class AgenticIopsStreamingStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const mediaDomains = parseMediaDomains(
      this.node.tryGetContext('mediaDomains') ?? DEFAULT_MEDIA_DOMAINS,
    );
    const allowWrites = `${this.node.tryGetContext('allowWrites') ?? 'false'}` === 'true';
    const writeTag = readWriteTag(this.node.tryGetContext('writeTag'));
    const jwt = readJwtSettings(
      this.node.tryGetContext('jwtDiscoveryUrl'),
      this.node.tryGetContext('jwtClientIds'),
    );
    const invokerRoleName = this.node.tryGetContext('invokerRoleName');
    if (jwt && invokerRoleName) {
      throw new Error('invokerRoleName grants IAM invoke, which a JWT-authorized runtime refuses. Pass one of them.');
    }

    // Context, not CfnParameters: the security diff synthesizes with the same -c options as
    // the deploy, so the IAM it shows names these exact models (T60).
    const agentModelId = readModelId('agentModelId', this.node.tryGetContext('agentModelId'),
      'us.anthropic.claude-sonnet-4-6');
    const thumbnailModelId = readModelId('thumbnailModelId', this.node.tryGetContext('thumbnailModelId'),
      'us.anthropic.claude-haiku-4-5-20251001-v1:0');

    const image = new ecr_assets.DockerImageAsset(this, 'RuntimeDockerImage', {
      directory: REPOSITORY_ROOT,
      file: 'samples/agentic-iops-streaming/Dockerfile',
      platform: ecr_assets.Platform.LINUX_ARM64,
      exclude: [
        '**/.git', '**/.venv', '**/node_modules', '**/cdk.out', '**/__pycache__',
        '**/.pytest_cache', '**/.cache', '**/.hub-sessions', '**/.mypy_cache', '**/.ruff_cache',
        '**/eval-results.json', '.claude', '.kiro', 'docs/images', 'samples/hydrolix',
        'samples/agentic-iops-streaming/cdk', 'samples/*/tests',
      ],
    });

    const signingKey = new secretsmanager.Secret(this, 'ApprovalSigningKey', {
      description: 'HMAC key the coordinator signs operator approvals with (APPROVAL_SIGNING_KEY)',
      generateSecretString: { passwordLength: 64, excludePunctuation: true },
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const role = new iam.Role(this, 'AgentCoreExecutionRole', {
      assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com'),
      description: `agentic-iops-streaming runtime: ${mediaDomains.join(', ')}`,
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
      for (const statement of this.packStatements(domain, allowWrites, thumbnailModelId, writeTag)) {
        role.addToPolicy(statement);
      }
    }

    const suffix = RESOURCE_NAME_SUFFIX;
    const memory = new bedrockagentcore.CfnMemory(this, 'AgenticIopsMemory', {
      name: `AgenticIopsStreamingMemory_${suffix}`,
      eventExpiryDuration: 7,
      memoryExecutionRoleArn: role.roleArn,
      description: 'Sessions and paused approvals of agentic-iops-streaming',
    });

    const runtime = new bedrockagentcore.CfnRuntime(this, 'AgenticIopsRuntime', {
      agentRuntimeName: RUNTIME_NAME,
      agentRuntimeArtifact: { containerConfiguration: { containerUri: image.imageUri } },
      networkConfiguration: { networkMode: 'PUBLIC' },
      roleArn: role.roleArn,
      description: 'agentic-iops-streaming: one Strands agent over the selected domain packs',
      // JWT mode forwards only the verified token, so a caller cannot supply an actor header.
      requestHeaderConfiguration: { requestHeaderAllowlist: [jwt ? AUTHORIZATION_HEADER : ACTOR_HEADER] },
      authorizerConfiguration: jwt
        ? { customJwtAuthorizer: { discoveryUrl: jwt.discoveryUrl, allowedClients: jwt.clientIds } }
        : undefined,
      environmentVariables: {
        AWS_REGION: this.region,
        AGENT_MODEL_ID: agentModelId,
        THUMBNAIL_MODEL_ID: thumbnailModelId,
        MEDIA_DOMAINS: mediaDomains.join(','),
        // Visual quality sampling inside one agent turn (the MCP default is 10 frames in 30 s).
        VISUAL_QUALITY_FRAMES: '8',
        VISUAL_QUALITY_WINDOW_SECONDS: '20',
        ALLOW_WRITES: allowWrites ? 'true' : 'false',
        MEMORY_ID: memory.attrMemoryId,
        APPROVAL_SIGNING_KEY_SECRET_ARN: signingKey.secretArn,
        ...(jwt ? { AGENTIC_IOPS_JWT_ISSUER: jwt.issuer, AGENTIC_IOPS_JWT_ALLOWED_CLIENTS: jwt.clientIds.join(',') } : {}),
      },
    });
    for (const statement of this.runtimeStatements(memory.attrMemoryArn, agentModelId)) {
      role.addToPolicy(statement);
    }
    // AgentCore validates the role when it creates the runtime (it pulls the image from ECR
    // then), and RoleArn alone doesn't order the runtime after the role's DefaultPolicy:
    // without this, both can be created in the same second and the deploy rolls back (RB14).
    // No cycle: the policy depends on the role and the memory, never on the runtime.
    runtime.node.addDependency(role.node.findChild('DefaultPolicy'));

    const endpoint = new bedrockagentcore.CfnRuntimeEndpoint(this, 'AgenticIopsEndpoint', {
      agentRuntimeId: runtime.attrAgentRuntimeId,
      name: `AgenticIopsStreamingEndpoint_${suffix}`,
      description: 'Endpoint for invoking agentic-iops-streaming',
    });

    if (!jwt) {
      // Who may invoke: only principals with this policy (or broader IAM). The actor header is
      // caller-supplied, so actor isolation holds only among these principals (extend_agentic_iops_streaming.md §1).
      const invokePolicy = new iam.ManagedPolicy(this, 'InvokeHubPolicy', {
        description: 'Invoke agentic-iops-streaming runtime and its endpoint, nothing else',
        statements: [
          new iam.PolicyStatement({
            sid: 'InvokeHub',
            actions: ['bedrock-agentcore:InvokeAgentRuntime'],
            resources: [runtime.attrAgentRuntimeArn, `${runtime.attrAgentRuntimeArn}/runtime-endpoint/*`],
          }),
        ],
      });
      if (invokerRoleName) {
        invokePolicy.attachToRole(iam.Role.fromRoleName(this, 'InvokerRole', `${invokerRoleName}`));
      }
      new cdk.CfnOutput(this, 'InvokePolicyArn', { value: invokePolicy.managedPolicyArn });
    }

    new cdk.CfnOutput(this, 'InboundAuth', { value: jwt ? 'jwt' : 'iam' });
    new cdk.CfnOutput(this, 'AgentRuntimeArn', { value: runtime.attrAgentRuntimeArn });
    new cdk.CfnOutput(this, 'AgentRuntimeId', { value: runtime.attrAgentRuntimeId });
    new cdk.CfnOutput(this, 'AgentEndpointName', { value: endpoint.name });
    new cdk.CfnOutput(this, 'MemoryId', { value: memory.attrMemoryId });
    new cdk.CfnOutput(this, 'MediaDomains', { value: mediaDomains.join(',') });
  }

  /**
   * What invoking one configured model needs (T60), following AWS's cross-Region inference
   * guidance: the inference profile in this account and Region, and the foundation model in
   * every Region the profile can route to. That set differs per geography and changes over
   * time, so the model ARN keeps the Region as `*`, but names the one model, derived from the
   * profile here and nowhere else. A bare foundation-model id gets only the model ARN.
   */
  private modelResources(modelId: string): string[] {
    const model = `arn:aws:bedrock:*::foundation-model/${baseModelId(modelId)}`;
    if (baseModelId(modelId) === modelId) {
      return [model];
    }
    return [`arn:aws:bedrock:${this.region}:${this.account}:inference-profile/${modelId}`, model];
  }

  /** What every agentic-iops-streaming runtime needs, whatever packs it loads. */
  private runtimeStatements(memoryArn: string, agentModelId: string): iam.PolicyStatement[] {
    // Only this runtime's own log groups (runtime ids are `<RUNTIME_NAME>-<suffix>`).
    const logGroup = `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/runtimes/${RUNTIME_NAME}-*`;
    return [
      new iam.PolicyStatement({
        sid: 'InvokeAgentModel',
        actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
        resources: this.modelResources(agentModelId),
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
        resources: [memoryArn], // this runtime's memory only
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
  private packStatements(
    domain: string,
    allowWrites: boolean,
    thumbnailModelId: string,
    writeTag?: WriteTag,
  ): iam.PolicyStatement[] {
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
            resources: statement.resources.flatMap((resource) =>
              resource === VISION_MODEL
                ? this.modelResources(thumbnailModelId)
                : [resource.split('{region}').join(this.region).split('{account}').join(this.account)],
            ),
            conditions: kind === 'Write' && writeTag
              ? { StringEquals: { [`aws:ResourceTag/${writeTag.key}`]: writeTag.value } }
              : undefined,
          }),
      ),
    );
  }
}

export interface JwtSettings {
  discoveryUrl: string;
  issuer: string;
  clientIds: string[];
}

/** Both or neither: a discovery URL without client ids would admit any client of the provider. */
export function readJwtSettings(discoveryUrl?: string, clientIds?: string): JwtSettings | undefined {
  const url = `${discoveryUrl ?? ''}`.trim();
  const clients = `${clientIds ?? ''}`.split(',').map((c) => c.trim()).filter(Boolean);
  if (!url && clients.length === 0) {
    return undefined;
  }
  if (!/^https:\/\/\S+\/\.well-known\/openid-configuration$/.test(url) || clients.length === 0) {
    throw new Error(
      'JWT auth needs both -c jwtDiscoveryUrl=https://<issuer>/.well-known/openid-configuration '
      + 'and -c jwtClientIds=<client id>[,<client id>].',
    );
  }
  // OpenID Connect discovery: the issuer is the discovery URL without the well-known suffix.
  return { discoveryUrl: url, issuer: url.slice(0, -DISCOVERY_SUFFIX.length), clientIds: clients };
}

export function parseMediaDomains(value: string): string[] {
  const domains = [...new Set(`${value}`.split(',').map((d) => d.trim()).filter(Boolean))];
  if (domains.length === 0) {
    throw new Error('mediaDomains is empty. Pass -c mediaDomains=medialive (comma-separated).');
  }
  return domains;
}

export function readWriteTag(value?: string): WriteTag | undefined {
  const raw = `${value ?? ''}`.trim();
  if (!raw) {
    return undefined;
  }
  const separator = raw.indexOf('=');
  const key = separator < 0 ? '' : raw.slice(0, separator).trim();
  const tagValue = separator < 0 ? '' : raw.slice(separator + 1).trim();
  const validKey = /^[A-Za-z0-9_.:/+@-]{1,128}$/.test(key);
  const validValue = tagValue.length <= 256 && !/[\u0000-\u001f\u007f]/.test(tagValue);
  if (!validKey || !tagValue || !validValue) {
    throw new Error(
      'writeTag must be Key=Value with an ASCII tag key (1-128 characters) '
      + 'and a non-empty value of at most 256 characters.',
    );
  }
  return { key, value: tagValue };
}

// Pack domains whose sample folder is not named after the domain.
const PACK_FOLDERS: Record<string, string> = { hls: 'hls-doctor' };

export function readPackPermissions(domain: string): PackPermissions {
  const folder = PACK_FOLDERS[domain] ?? domain;
  const file = path.join(SAMPLES_DIR, folder, 'iam_permissions.json');
  if (!/^[a-z0-9-]+$/.test(folder) || !fs.existsSync(file)) {
    throw new Error(`Unknown media domain "${domain}": samples/${folder}/iam_permissions.json not found.`);
  }
  return JSON.parse(fs.readFileSync(file, 'utf8')) as PackPermissions;
}

// A pack's Bedrock grant: the thumbnail (vision) model agentic-iops-streaming is configured with, nothing else.
const VISION_MODEL = '{vision_model}';
// The repository's one model-id rule (T72), shared with the deploy scripts and the Hydrolix
// stack: model and cross-Region profile ids only, so no value can widen a grant.
const MODEL_ID_RULE = JSON.parse(
  fs.readFileSync(path.join(REPOSITORY_ROOT, 'scripts', 'model_id_rule.json'), 'utf8'),
) as { profile_prefixes: string[]; pattern: string };
const MODEL_ID_PATTERN = new RegExp(MODEL_ID_RULE.pattern);
const PROFILE_PREFIXES = new Set(MODEL_ID_RULE.profile_prefixes);

export function readModelId(name: string, value: unknown, fallback: string): string {
  const id = `${value ?? ''}`.trim() || fallback;
  if (!MODEL_ID_PATTERN.test(id)) {
    throw new Error(`${name} must be a Bedrock model or inference-profile id, for example ${fallback}; got '${id}'.`);
  }
  return id;
}

/** The foundation model an id routes to: a profile without its prefix, or the model itself. */
export function baseModelId(id: string): string {
  const [prefix, ...rest] = id.split('.');
  return PROFILE_PREFIXES.has(prefix) && rest.length >= 2 ? rest.join('.') : id;
}

function pascalCase(value: string): string {
  return value.split(/[^a-z0-9]/i).map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join('');
}
