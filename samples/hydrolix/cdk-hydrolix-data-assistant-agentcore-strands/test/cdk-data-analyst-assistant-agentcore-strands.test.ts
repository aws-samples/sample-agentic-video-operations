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

test("query records are keyed by the verified user and only ever written (T41)", () => {
  const template = synthesizeTemplate();
  const tables = template.findResources("AWS::DynamoDB::Table");
  const [recordsId] = Object.keys(tables).filter((id) => id.startsWith("QueryRecords"));
  expect(tables[recordsId].Properties.KeySchema).toEqual([
    { AttributeName: "actor_id", KeyType: "HASH" },
    { AttributeName: "recorded_at", KeyType: "RANGE" },
  ]);
  expect(tables[recordsId].DeletionPolicy).toBe("Delete"); // `just destroy` removes it

  const statements = policyStatements(template);
  const dynamoActions = statements
    .flatMap((statement: any) => ([] as string[]).concat(statement.Action))
    .filter((action: string) => action.startsWith("dynamodb:"));
  // No Query, Scan, GetItem or UpdateItem: no role in this stack can read one user's
  // records for another. The web app gets its records in the response stream.
  expect(dynamoActions).toEqual(["dynamodb:PutItem"]);
  const environment = template.findResources("AWS::BedrockAgentCore::Runtime");
  expect(JSON.stringify(environment)).toContain(`"QUESTION_ANSWERS_TABLE":{"Ref":"${recordsId}"}`);
});

test("the earlier results table is kept as it was, retained, and granted to nobody (T41)", () => {
  const template = synthesizeTemplate();
  const tables = template.findResources("AWS::DynamoDB::Table");
  // The logical id earlier versions deployed: unchanged, so upgrading doesn't replace it.
  const retired = tables["RawQueryResults82B00746"];
  expect(retired.Properties.KeySchema).toEqual([
    { AttributeName: "id", KeyType: "HASH" },
    { AttributeName: "my_timestamp", KeyType: "RANGE" },
  ]);
  // CloudFormation applies the deployed template's policy to a dropped resource, so the
  // table must carry Retain in this release, before any release drops it.
  expect(retired.DeletionPolicy).toBe("Retain");
  expect(retired.UpdateReplacePolicy).toBe("Retain");
  expect(JSON.stringify(policyStatements(template))).not.toContain("RawQueryResults82B00746");
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
    "Fn::GetAtt": [expect.stringMatching(/^QueryRecords/), "Arn"],
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

describe("Bedrock invoke is scoped to the configured model (T71)", () => {
  const template = synthesizeTemplate().toJSON();
  const grant = () =>
    policyStatements(synthesizeTemplate()).filter((statement: any) =>
      ([] as string[]).concat(statement.Action).some((a: string) => a.startsWith("bedrock:Invoke")),
    );

  /** Evaluates the template's intrinsics the way CloudFormation would, for one model id. */
  function evaluate(node: any, modelId: string): any {
    const pseudo: Record<string, string> = {
      "AWS::Region": "us-west-2",
      "AWS::AccountId": "111122223333",
      BedrockModelId: modelId,
    };
    const run = (value: any): any => {
      if (Array.isArray(value)) return value.map(run);
      if (value === null || typeof value !== "object") return value;
      const [name] = Object.keys(value);
      const args = value[name];
      switch (name) {
        case "Ref": return pseudo[args];
        case "Condition": return run(template.Conditions[args]);
        case "Fn::Split": return run(args[1]).split(args[0]);
        case "Fn::Select": {
          const list = run(args[1]);
          if (args[0] >= list.length) throw new Error(`Fn::Select ${args[0]} out of range`);
          return list[args[0]];
        }
        case "Fn::Join": return run(args[1]).join(args[0]);
        case "Fn::Equals": return run(args[0]) === run(args[1]);
        case "Fn::Or": return args.some((c: any) => run(c));
        case "Fn::If": return run(template.Conditions[args[0]]) ? run(args[1]) : run(args[2]);
        default: throw new Error(`unhandled ${name}`);
      }
    };
    return run(node);
  }
  const resourcesFor = (modelId: string) => grant().flatMap((s: any) => [].concat(evaluate(s.Resource, modelId)));

  test("one statement, and no model or profile wildcard anywhere", () => {
    expect(grant()).toHaveLength(1);
    const text = JSON.stringify(policyStatements(synthesizeTemplate()));
    expect(text).not.toContain("foundation-model/*");
    expect(text).not.toContain("inference-profile/*");
    expect(text).not.toMatch(/arn:aws:bedrock:[^"]*:\*"/);
  });

  test("a profile id gets its profile here and the model behind it anywhere", () => {
    expect(resourcesFor("us.anthropic.claude-sonnet-4-6")).toEqual([
      "arn:aws:bedrock:us-west-2:111122223333:inference-profile/us.anthropic.claude-sonnet-4-6",
      "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-6",
    ]);
    const eu = ["eu", "anthropic.claude-sonnet-4-6"].join(".");
    expect(resourcesFor(eu)).toEqual([
      `arn:aws:bedrock:us-west-2:111122223333:inference-profile/${eu}`,
      "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-6",
    ]);
  });

  test("the model is derived from the one parameter, so it can't mismatch", () => {
    // There is no base-model parameter to pair wrongly: every prefix maps to its own model.
    expect(Object.keys(template.Parameters)).not.toContain("BedrockBaseModelId");
    for (const prefix of ["us", "eu", "apac", "us-gov", "jp", "au", "ca", "global"]) {
      expect(resourcesFor(`${prefix}.meta.llama3-70b-instruct-v1:0`)[1]).toBe(
        "arn:aws:bedrock:*::foundation-model/meta.llama3-70b-instruct-v1:0",
      );
    }
  });

  test("a bare model id gets only that foundation model", () => {
    expect(resourcesFor("meta.llama3-70b-instruct-v1:0")).toEqual([
      "arn:aws:bedrock:*::foundation-model/meta.llama3-70b-instruct-v1:0",
    ]);
  });

  test("the deploy context sets the parameter's default, and a bad one fails synth", () => {
    // T71 review: the security diff and the deploy both synthesize with -c agentModelId.
    const eu = ["eu", "anthropic.claude-sonnet-4-6"].join(".");
    const custom = synthesizeTemplate({ agentModelId: eu }).toJSON();
    expect(custom.Parameters.BedrockModelId.Default).toBe(eu);
    expect(template.Parameters.BedrockModelId.Default).toBe("us.anthropic.claude-sonnet-4-6");
    for (const bad of ["*", "us.anthropic", "arn:aws:bedrock:*::foundation-model/*"]) {
      expect(() => synthesizeTemplate({ agentModelId: bad })).toThrow(/agentModelId must be/);
    }
  });

  test("the parameter accepts only ids the derivation can read", () => {
    const pattern = new RegExp(template.Parameters.BedrockModelId.AllowedPattern);
    for (const good of ["us.anthropic.claude-sonnet-4-6", "anthropic.claude-sonnet-4-6",
      "us-gov.meta.llama3-70b-instruct-v1:0", "global.amazon.titan-text-premier-v1:0"]) {
      expect(pattern.test(good)).toBe(true);
      expect(() => resourcesFor(good)).not.toThrow();
    }
    for (const bad of ["*", "anthropic.*", "a/b", "", "us.anthropic", "anthropic",
      "arn:aws:bedrock:*::foundation-model/*", "us.anthropic.claude.extra", "us..x"]) {
      expect(pattern.test(bad)).toBe(false);
    }
  });
});

test("the runtime is created after every policy on its role (RB14)", () => {
  const resources = synthesizeTemplate().toJSON().Resources;
  const [runtimeId] = Object.keys(resources).filter(
    (id) => resources[id].Type === "AWS::BedrockAgentCore::Runtime",
  );
  const roleId = resources[runtimeId].Properties.RoleArn["Fn::GetAtt"][0];
  const attached = Object.keys(resources).filter(
    (id) =>
      ["AWS::IAM::Policy", "AWS::IAM::ManagedPolicy"].includes(resources[id].Type) &&
      (resources[id].Properties.Roles ?? []).some((role: any) => role.Ref === roleId),
  );
  expect(attached.length).toBeGreaterThan(0);
  expect(resources[runtimeId].DependsOn).toEqual(expect.arrayContaining(attached));
});
