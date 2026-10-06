import * as cdk from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";

import {
  AUTHORIZATION_HEADER,
  CdkHydrolixDataAssistantAgentcoreStrandsStack,
  readJwtSettings,
} from "../cdklib/cdk-hydrolix-data-assistant-agentcore-strands-stack";

function synthesizeTemplate(context: Record<string, string> = {}): Template {
  const app = new cdk.App({ context });
  const stack = new CdkHydrolixDataAssistantAgentcoreStrandsStack(
    app,
    "HydrolixTestStack",
  );
  return Template.fromStack(stack);
}

function policyStatements(template: Template): any[] {
  const roleStatements = Object.values(
    template.findResources("AWS::IAM::Role"),
  ).flatMap((role: any) =>
    (role.Properties.Policies ?? []).flatMap(
      (policy: any) => policy.PolicyDocument.Statement,
    ),
  );
  const attachedStatements = Object.values(
    template.findResources("AWS::IAM::Policy"),
  ).flatMap((policy: any) => policy.Properties.PolicyDocument.Statement);
  return [...roleStatements, ...attachedStatements];
}

test("the Hydrolix secret uses a generated physical name", () => {
  const resources = synthesizeTemplate().findResources(
    "AWS::SecretsManager::Secret",
  );
  const [secret] = Object.values(resources);

  expect(secret.Properties.Name).toBeUndefined();
});

test("the Hydrolix table parameter accepts only database.table", () => {
  const parameter = synthesizeTemplate().toJSON().Parameters.HydrolixTable;
  const pattern = new RegExp(parameter.AllowedPattern);

  for (const good of ["video.cmcd", "my-project.cdn_logs", "systems.cmcd", "video.system"]) {
    expect(pattern.test(good)).toBe(true);
  }
  for (const bad of [
    "cmcd",
    "videoXcmcd",
    "a.b.c",
    "video.cmcd; DROP",
    "",
    "system.tables",
    "SYSTEM.tables",
    "System.users",
    "information_schema.tables",
    "INFORMATION_SCHEMA.TABLES",
    "_internal.cmcd",
    "video._cmcd",
  ]) {
    expect(pattern.test(bad)).toBe(false);
  }
});

test("the runtime can pull but never push its exact asset repository", () => {
  const statements = policyStatements(synthesizeTemplate());
  const ecrActions = statements
    .flatMap((statement: any) => ([] as string[]).concat(statement.Action))
    .filter((action: string) => action.startsWith("ecr:"));

  expect(ecrActions).toEqual(expect.arrayContaining([
    "ecr:BatchCheckLayerAvailability",
    "ecr:BatchGetImage",
    "ecr:GetDownloadUrlForLayer",
    "ecr:GetAuthorizationToken",
  ]));
  expect(ecrActions).not.toEqual(expect.arrayContaining([
    "ecr:PutImage",
    "ecr:InitiateLayerUpload",
    "ecr:UploadLayerPart",
    "ecr:CompleteLayerUpload",
  ]));
  const pull = statements.find((statement: any) =>
    ([] as string[]).concat(statement.Action).includes("ecr:BatchGetImage"),
  );
  expect(JSON.stringify(pull.Resource)).toContain("cdk-hnb659fds-container-assets-");
  expect(JSON.stringify(pull.Resource)).not.toContain("repository/*");
});

test("the runtime receives no workload identity token authority", () => {
  const actions = policyStatements(synthesizeTemplate()).flatMap(
    (statement: any) => ([] as string[]).concat(statement.Action),
  );

  expect(
    actions.filter((action: string) =>
      action.startsWith("bedrock-agentcore:GetWorkloadAccessToken"),
    ),
  ).toEqual([]);
});

test("runtime writes name only its table memory and log groups", () => {
  const template = synthesizeTemplate();
  const statements = policyStatements(template);

  const table = statements.find((statement: any) =>
    ([] as string[]).concat(statement.Action).includes("dynamodb:PutItem"),
  );
  expect(table.Resource).toEqual({
    "Fn::GetAtt": [expect.stringMatching(/^RawQueryResults/), "Arn"],
  });

  const memory = statements.find(
    (statement: any) => statement.Sid === "BedrockAgentCoreMemoryAccess",
  );
  expect(memory.Resource).toEqual({
    "Fn::GetAtt": [expect.stringMatching(/^AgentMemory/), "MemoryArn"],
  });

  const logs = statements.filter((statement: any) =>
    ([] as string[]).concat(statement.Action).some(
      (action: string) => action.startsWith("logs:") && action !== "logs:DescribeLogGroups",
    ),
  );
  expect(JSON.stringify(logs)).toContain("runtimes/HydrolixRuntime_");
  expect(JSON.stringify(logs)).not.toContain("runtimes/*");
});

describe("inbound auth (RB9)", () => {
  const issuer = "https://cognito-idp.us-west-2.amazonaws.com/us-west-2_EXAMPLE";
  const jwtContext = {
    jwtDiscoveryUrl: `${issuer}/.well-known/openid-configuration`,
    jwtClientIds: "client-a, client-b",
  };

  function runtimeProperties(template: Template): any {
    const [runtime] = Object.values(template.findResources("AWS::BedrockAgentCore::Runtime")) as any[];
    return runtime.Properties;
  }

  test("is IAM by default: no authorizer, no forwarded caller header, no issuer", () => {
    const template = synthesizeTemplate();
    const runtime = runtimeProperties(template);
    expect(runtime.AuthorizerConfiguration).toBeUndefined();
    expect(runtime.RequestHeaderConfiguration).toBeUndefined();
    expect(runtime.EnvironmentVariables).not.toHaveProperty("HYDROLIX_JWT_ISSUER");
    template.hasOutput("InboundAuth", { Value: "iam" });
  });

  test("JWT mode accepts only the pool's tokens and forwards only the token", () => {
    const template = synthesizeTemplate(jwtContext);
    const runtime = runtimeProperties(template);
    expect(runtime.AuthorizerConfiguration).toEqual({
      CustomJWTAuthorizer: {
        DiscoveryUrl: jwtContext.jwtDiscoveryUrl,
        AllowedClients: ["client-a", "client-b"],
      },
    });
    expect(runtime.RequestHeaderConfiguration).toEqual({
      RequestHeaderAllowlist: [AUTHORIZATION_HEADER],
    });
    expect(runtime.EnvironmentVariables.HYDROLIX_JWT_ISSUER).toBe(issuer);
    expect(runtime.EnvironmentVariables.HYDROLIX_JWT_ALLOWED_CLIENTS).toBe("client-a,client-b");
    template.hasOutput("InboundAuth", { Value: "jwt" });
  });

  test.each([
    [`${issuer}/.well-known/openid-configuration`, ""],
    ["", "client-a"],
    ["http://issuer.example.com/.well-known/openid-configuration", "client-a"],
    [issuer, "client-a"],
  ])("needs an https discovery URL and a client id (%s, %s)", (url, clients) => {
    expect(() => readJwtSettings(url, clients)).toThrow(/jwtDiscoveryUrl/);
  });
});

test("runtime metrics are limited to the AgentCore namespace", () => {
  const metrics = policyStatements(synthesizeTemplate()).find((statement: any) =>
    ([] as string[]).concat(statement.Action).includes("cloudwatch:PutMetricData"),
  );

  expect(metrics.Resource).toBe("*");
  expect(metrics.Condition).toEqual({
    StringEquals: {
      "cloudwatch:namespace": "bedrock-agentcore",
    },
  });
});

test("runtime inference profiles are limited to this region and account", () => {
  const invocation = policyStatements(synthesizeTemplate()).find(
    (statement: any) => statement.Sid === "BedrockModelInvocationMemory",
  );
  const resources = JSON.stringify(invocation.Resource);

  expect(resources).toContain("AWS::Region");
  expect(resources).toContain("AWS::AccountId");
  expect(resources).toContain("inference-profile/*");
  expect(resources).not.toContain("arn:aws:bedrock:*:*:inference-profile/*");
});
