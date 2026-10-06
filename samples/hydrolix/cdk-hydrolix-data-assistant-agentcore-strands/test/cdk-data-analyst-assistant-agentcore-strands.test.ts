import * as cdk from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";

import { CdkHydrolixDataAssistantAgentcoreStrandsStack } from "../cdklib/cdk-hydrolix-data-assistant-agentcore-strands-stack";

function synthesizeTemplate(): Template {
  const app = new cdk.App();
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
