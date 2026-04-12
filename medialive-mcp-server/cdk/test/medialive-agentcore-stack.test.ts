import * as cdk from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { MediaLiveAgentCoreStack } from '../lib/medialive-agentcore-stack';

let template: Template;

beforeAll(() => {
  const app = new cdk.App();
  const stack = new MediaLiveAgentCoreStack(app, 'TestStack');
  template = Template.fromStack(stack);
});

describe('CfnParameters', () => {
  test('BedrockModelId parameter exists with correct default', () => {
    template.hasParameter('BedrockModelId', {
      Type: 'String',
      Default: 'us.anthropic.claude-sonnet-4-6',
    });
  });

  test('ThumbnailModelId parameter exists with correct default', () => {
    template.hasParameter('ThumbnailModelId', {
      Type: 'String',
      Default: 'us.anthropic.claude-haiku-4-5-20251001-v1:0',
    });
  });

  test('DefaultChannelId parameter exists with no default', () => {
    template.hasParameter('DefaultChannelId', {
      Type: 'String',
    });
    // Verify no default is set
    const params = template.toJSON().Parameters;
    expect(params.DefaultChannelId.Default).toBeUndefined();
  });
});

describe('IAM Execution Role', () => {
  test('trust policy uses bedrock-agentcore.amazonaws.com with AssumeRole + TagSession', () => {
    template.hasResourceProperties('AWS::IAM::Role', {
      AssumeRolePolicyDocument: {
        Statement: [
          {
            Sid: 'Statement1',
            Effect: 'Allow',
            Principal: { Service: 'bedrock-agentcore.amazonaws.com' },
            Action: ['sts:AssumeRole', 'sts:TagSession'],
          },
        ],
      },
    });
  });

  test('policy includes all 10 MediaLive actions', () => {
    const resources = template.toJSON().Resources;
    const roleKey = Object.keys(resources).find(
      (k) => resources[k].Type === 'AWS::IAM::Role',
    )!;
    const statements = resources[roleKey].Properties.Policies[0].PolicyDocument.Statement;
    const mlStmt = statements.find((s: any) => s.Sid === 'MediaLiveAccess');
    expect(mlStmt).toBeDefined();
    const expected = [
      'medialive:ListChannels', 'medialive:DescribeChannel',
      'medialive:StartChannel', 'medialive:StopChannel',
      'medialive:DescribeThumbnails', 'medialive:DescribeSchedule',
      'medialive:BatchUpdateSchedule', 'medialive:DeleteSchedule',
      'medialive:ListInputs', 'medialive:DescribeInput',
    ];
    for (const action of expected) {
      expect(mlStmt.Action).toContain(action);
    }
  });

  test('no policy statement uses Action: *', () => {
    const resources = template.toJSON().Resources;
    const roleKey = Object.keys(resources).find(
      (k) => resources[k].Type === 'AWS::IAM::Role',
    )!;
    const statements = resources[roleKey].Properties.Policies[0].PolicyDocument.Statement;
    for (const stmt of statements) {
      if (typeof stmt.Action === 'string') {
        expect(stmt.Action).not.toBe('*');
      } else if (Array.isArray(stmt.Action)) {
        expect(stmt.Action).not.toContain('*');
      }
    }
  });
});

describe('AgentCore Memory', () => {
  test('CfnMemory has 7-day event expiry', () => {
    template.hasResourceProperties('AWS::BedrockAgentCore::Memory', {
      EventExpiryDuration: 7,
    });
  });
});

describe('AgentCore Runtime', () => {
  test('CfnRuntime has PUBLIC network mode', () => {
    template.hasResourceProperties('AWS::BedrockAgentCore::Runtime', {
      NetworkConfiguration: { NetworkMode: 'PUBLIC' },
    });
  });

  test('CfnRuntime has all 5 environment variables', () => {
    const resources = template.toJSON().Resources;
    const rtKey = Object.keys(resources).find(
      (k) => resources[k].Type === 'AWS::BedrockAgentCore::Runtime',
    )!;
    const envVars = resources[rtKey].Properties.EnvironmentVariables;
    expect(envVars).toHaveProperty('AGENT_MODEL_ID');
    expect(envVars).toHaveProperty('THUMBNAIL_MODEL_ID');
    expect(envVars).toHaveProperty('MEDIALIVE_DEFAULT_CHANNEL_ID');
    expect(envVars).toHaveProperty('MEMORY_ID');
    expect(envVars).toHaveProperty('AWS_REGION');
  });
});

describe('AgentCore Runtime Endpoint', () => {
  test('CfnRuntimeEndpoint exists', () => {
    template.resourceCountIs('AWS::BedrockAgentCore::RuntimeEndpoint', 1);
  });
});

describe('CfnOutputs', () => {
  test('MemoryId output exists', () => { template.hasOutput('MemoryId', {}); });
  test('AgentRuntimeArn output exists', () => { template.hasOutput('AgentRuntimeArn', {}); });
  test('AgentEndpointName output exists', () => { template.hasOutput('AgentEndpointName', {}); });
});

describe('Design constraints', () => {
  test('zero DynamoDB tables', () => { template.resourceCountIs('AWS::DynamoDB::Table', 0); });
  test('zero Secrets Manager secrets', () => { template.resourceCountIs('AWS::SecretsManager::Secret', 0); });
});
