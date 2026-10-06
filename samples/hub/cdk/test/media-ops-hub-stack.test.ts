import * as cdk from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import {
  ACTOR_HEADER, AUTHORIZATION_HEADER, MediaOpsHubStack, RUNTIME_NAME, readJwtSettings,
  readPackPermissions, readWriteTag,
} from '../lib/media-ops-hub-stack';

function synth(context: Record<string, string> = {}): Template {
  const app = new cdk.App({ context });
  return Template.fromStack(new MediaOpsHubStack(app, 'TestHub'));
}

function runtimeEnvironment(template: Template): Record<string, unknown> {
  const runtimes = template.findResources('AWS::BedrockAgentCore::Runtime');
  const [runtime] = Object.values(runtimes);
  return runtime.Properties.EnvironmentVariables;
}

function roleStatements(template: Template): any[] {
  const policies = template.findResources('AWS::IAM::Policy');
  return Object.values(policies).flatMap((p: any) => p.Properties.PolicyDocument.Statement);
}

function actionsOf(statements: any[]): Set<string> {
  return new Set(statements.flatMap((s) => ([] as string[]).concat(s.Action)));
}

const defaultTemplate = synth();

describe('runtime environment', () => {
  test('sets the selected domains, writes off by default, memory and the signing-key secret', () => {
    const env = runtimeEnvironment(defaultTemplate);
    expect(env.MEDIA_DOMAINS).toBe('medialive,mediaconnect');
    expect(env.ALLOW_WRITES).toBe('false');
    expect(env.MEMORY_ID).toBeDefined();
    expect(env.APPROVAL_SIGNING_KEY_SECRET_ARN).toEqual({ Ref: expect.stringMatching(/^ApprovalSigningKey/) });
  });

  test('never sets HUB_LOCAL_MODE, DEMO or a plaintext APPROVAL_SIGNING_KEY', () => {
    for (const template of [defaultTemplate, synth({ allowWrites: 'true' })]) {
      const env = runtimeEnvironment(template);
      expect(env).not.toHaveProperty('HUB_LOCAL_MODE');
      expect(env).not.toHaveProperty('DEMO');
      expect(env).not.toHaveProperty('APPROVAL_SIGNING_KEY');
    }
  });

  test('the runtime samples visual quality in a short, bounded window', () => {
    const env = runtimeEnvironment(defaultTemplate);
    expect(env.VISUAL_QUALITY_FRAMES).toBe('8');
    expect(env.VISUAL_QUALITY_WINDOW_SECONDS).toBe('20');
  });

  test('model ids come from parameters, not literals in the runtime', () => {
    const env = runtimeEnvironment(defaultTemplate);
    expect(env.AGENT_MODEL_ID).toEqual({ Ref: 'BedrockModelId' });
    expect(env.THUMBNAIL_MODEL_ID).toEqual({ Ref: 'ThumbnailModelId' });
  });
});

describe('caller identity', () => {
  test('one managed policy grants invoke on this runtime only, attached to no role by default', () => {
    const policies = defaultTemplate.findResources('AWS::IAM::ManagedPolicy');
    const [policy] = Object.values(policies) as any[];
    const [statement] = policy.Properties.PolicyDocument.Statement;
    expect(Object.keys(policies)).toHaveLength(1);
    expect(statement.Action).toBe('bedrock-agentcore:InvokeAgentRuntime');
    expect(JSON.stringify(statement.Resource)).toContain('AgentRuntimeArn');
    expect(policy.Properties.Roles).toBeUndefined();
  });

  test('invokerRoleName attaches the invoke policy to exactly that role', () => {
    const template = synth({ invokerRoleName: 'media-ops-operator' });
    const [policy] = Object.values(template.findResources('AWS::IAM::ManagedPolicy')) as any[];
    expect(policy.Properties.Roles).toEqual(['media-ops-operator']);
  });

  test('the runtime forwards the actor header the hub requires', () => {
    defaultTemplate.hasResourceProperties('AWS::BedrockAgentCore::Runtime', {
      RequestHeaderConfiguration: { RequestHeaderAllowlist: [ACTOR_HEADER] },
    });
  });
});

describe('inbound JWT authorization', () => {
  const issuer = 'https://cognito-idp.us-west-2.amazonaws.com/us-west-2_EXAMPLE';
  const jwtContext = { jwtDiscoveryUrl: `${issuer}/.well-known/openid-configuration`, jwtClientIds: 'client-a, client-b' };
  const jwtTemplate = synth(jwtContext);

  test('is off by default: IAM callers, the actor header, no issuer for the hub', () => {
    const [runtime] = Object.values(defaultTemplate.findResources('AWS::BedrockAgentCore::Runtime')) as any[];
    expect(runtime.Properties.AuthorizerConfiguration).toBeUndefined();
    expect(runtimeEnvironment(defaultTemplate)).not.toHaveProperty('HUB_JWT_ISSUER');
    defaultTemplate.hasOutput('InboundAuth', { Value: 'iam' });
  });

  test('accepts only tokens from the provider and clients, and forwards only the token', () => {
    jwtTemplate.hasResourceProperties('AWS::BedrockAgentCore::Runtime', {
      AuthorizerConfiguration: {
        CustomJWTAuthorizer: { DiscoveryUrl: jwtContext.jwtDiscoveryUrl, AllowedClients: ['client-a', 'client-b'] },
      },
      RequestHeaderConfiguration: { RequestHeaderAllowlist: [AUTHORIZATION_HEADER] },
    });
    const env = runtimeEnvironment(jwtTemplate);
    expect(env.HUB_JWT_ISSUER).toBe(issuer);
    expect(env.HUB_JWT_ALLOWED_CLIENTS).toBe('client-a,client-b');
    expect(env).not.toHaveProperty('HUB_LOCAL_MODE');
    jwtTemplate.hasOutput('InboundAuth', { Value: 'jwt' });
  });

  test('creates no IAM invoke policy, which a JWT runtime would refuse anyway', () => {
    expect(Object.keys(jwtTemplate.findResources('AWS::IAM::ManagedPolicy'))).toHaveLength(0);
    expect(() => synth({ ...jwtContext, invokerRoleName: 'media-ops-operator' })).toThrow(/invokerRoleName/);
  });

  test.each([
    [`${issuer}/.well-known/openid-configuration`, ''],
    ['', 'client-a'],
    ['http://issuer.example.com/.well-known/openid-configuration', 'client-a'],
    [issuer, 'client-a'],
  ])('needs an https discovery URL and at least one client id (%s, %s)', (url, clients) => {
    expect(() => readJwtSettings(url, clients)).toThrow(/jwtDiscoveryUrl/);
  });
});

describe('approval signing key', () => {
  test('is one generated secret that only the runtime role can read', () => {
    defaultTemplate.resourceCountIs('AWS::SecretsManager::Secret', 1);
    const reads = roleStatements(defaultTemplate).filter((s) =>
      ([] as string[]).concat(s.Action).includes('secretsmanager:GetSecretValue'),
    );
    expect(reads).toHaveLength(1);
    expect(reads[0].Resource).toEqual({ Ref: expect.stringMatching(/^ApprovalSigningKey/) });
  });
});

describe('pack IAM', () => {
  const medialive = readPackPermissions('medialive');
  const readActions = new Set(medialive.read.flatMap((s) => s.actions));
  const writeActions = new Set(medialive.write.flatMap((s) => s.actions));

  test('grants every read statement of each default pack', () => {
    const granted = actionsOf(roleStatements(defaultTemplate));
    for (const domain of ['medialive', 'mediaconnect']) {
      for (const action of readPackPermissions(domain).read.flatMap((s) => s.actions)) {
        expect(granted).toContain(action);
      }
    }
  });

  test('a single selected pack gets only its own statements', () => {
    const granted = actionsOf(roleStatements(synth({ mediaDomains: 'medialive' })));
    expect(granted).not.toContain('mediaconnect:ListFlows');
    expect(runtimeEnvironment(synth({ mediaDomains: 'medialive' })).MEDIA_DOMAINS).toBe('medialive');
  });

  test('grants no write action unless allowWrites is set', () => {
    const granted = actionsOf(roleStatements(defaultTemplate));
    for (const action of writeActions) {
      expect(granted).not.toContain(action);
    }
  });

  test('grants the write statements and ALLOW_WRITES=true with allowWrites', () => {
    const template = synth({ allowWrites: 'true' });
    const granted = actionsOf(roleStatements(template));
    for (const action of writeActions) {
      expect(granted).toContain(action);
    }
    expect(runtimeEnvironment(template).ALLOW_WRITES).toBe('true');
    for (const statement of roleStatements(template).filter((item) => /Write\d+$/.test(item.Sid))) {
      expect(statement.Condition).toBeUndefined();
    }
  });

  test('optionally limits every pack write to resources with one exact tag', () => {
    const statements = roleStatements(
      synth({ allowWrites: 'true', writeTag: 'MediaOpsManaged=true' }),
    );
    const packWrites = statements.filter((item) => /^(Medialive|Mediaconnect)Write\d+$/.test(item.Sid));
    const packReads = statements.filter((item) => /^(Medialive|Mediaconnect)Read\d+$/.test(item.Sid));

    expect(packWrites).toHaveLength(2);
    for (const statement of packWrites) {
      expect(statement.Condition).toEqual({
        StringEquals: { 'aws:ResourceTag/MediaOpsManaged': 'true' },
      });
    }
    for (const statement of packReads) {
      expect(statement.Condition).toBeUndefined();
    }
  });

  test.each(['missing-value', '=value', 'bad key=value', 'key='])(
    'rejects an invalid write tag before synth (%s)',
    (writeTag) => {
      expect(() => synth({ allowWrites: 'true', writeTag })).toThrow(/writeTag must be Key=Value/);
    },
  );

  test('parses a tag value containing an equals sign', () => {
    expect(readWriteTag('MediaOpsScope=live=primary')).toEqual({
      key: 'MediaOpsScope',
      value: 'live=primary',
    });
  });

  test('fills in region and account, leaving no template placeholder', () => {
    const json = JSON.stringify(roleStatements(defaultTemplate));
    expect(json).not.toContain('{region}');
    expect(json).not.toContain('{account}');
  });

  test('an unknown domain fails synth with the missing file named', () => {
    expect(() => synth({ mediaDomains: 'medialive,nosuchpack' })).toThrow(
      /samples\/nosuchpack\/iam_permissions.json/,
    );
  });
});

describe("runtime writes are scoped to the hub's own resources", () => {
  test('memory actions name only the hub memory and logs only this runtime', () => {
    const statements = roleStatements(defaultTemplate);
    const memory = statements.find((s: any) => s.Sid === 'UseHubMemory');
    expect(memory.Resource).toEqual({ 'Fn::GetAtt': [expect.stringMatching(/^HubMemory/), 'MemoryArn'] });
    const logs = statements.find((s: any) => s.Sid === 'WriteRuntimeLogs');
    expect(JSON.stringify(logs.Resource)).toContain(`runtimes/${RUNTIME_NAME}-*`);
    expect(JSON.stringify(logs.Resource)).not.toContain('runtimes/*');
  });
});

describe('trust policy', () => {
  test('the runtime role has no workload-identity token actions', () => {
    const granted = actionsOf(roleStatements(defaultTemplate));
    for (const action of granted) {
      expect(action).not.toMatch(/^bedrock-agentcore:GetWorkloadAccessToken/);
    }
  });

  test('the runtime has the fixed name the destroy script scopes its log cleanup to', () => {
    defaultTemplate.hasResourceProperties('AWS::BedrockAgentCore::Runtime', {
      AgentRuntimeName: RUNTIME_NAME,
    });
  });

  test('only bedrock-agentcore in this account may assume the role', () => {
    const roles = defaultTemplate.findResources('AWS::IAM::Role');
    const [role] = Object.values(roles) as any[];
    const [statement] = role.Properties.AssumeRolePolicyDocument.Statement;
    expect(statement.Principal).toEqual({ Service: 'bedrock-agentcore.amazonaws.com' });
    expect(statement.Condition.StringEquals['aws:SourceAccount']).toEqual({ Ref: 'AWS::AccountId' });
  });

  test('no statement allows every action or uses a wildcard principal', () => {
    for (const statement of roleStatements(defaultTemplate)) {
      expect(([] as string[]).concat(statement.Action)).not.toContain('*');
      expect(statement.Principal).toBeUndefined();
    }
  });
});
