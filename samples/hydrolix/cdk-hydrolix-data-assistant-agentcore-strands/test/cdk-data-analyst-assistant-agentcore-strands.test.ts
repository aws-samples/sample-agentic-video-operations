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

test("the Hydrolix secret uses a generated physical name", () => {
  const resources = synthesizeTemplate().findResources(
    "AWS::SecretsManager::Secret",
  );
  const [secret] = Object.values(resources);

  expect(secret.Properties.Name).toBeUndefined();
});
