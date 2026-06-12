#!/usr/bin/env node
import "source-map-support/register";
import * as cdk from "aws-cdk-lib";
import { MediaServicesLangChainStack } from "../lib/media-services-langchain-stack";

const app = new cdk.App();
new MediaServicesLangChainStack(app, "MediaServicesLangChainStack", {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION || "us-west-2",
  },
});
