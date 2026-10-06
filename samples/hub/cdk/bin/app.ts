#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { MediaOpsHubStack } from '../lib/media-ops-hub-stack';

const app = new cdk.App();
new MediaOpsHubStack(app, 'MediaOpsHubStack', {
  description: 'Media ops hub: one Strands agent on AgentCore over the selected domain packs',
});
