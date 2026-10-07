#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { AgenticIopsStreamingStack } from '../lib/agentic-iops-streaming-stack';

const app = new cdk.App();
new AgenticIopsStreamingStack(app, 'AgenticIopsStreamingStack', {
  description: 'agentic-iops-streaming: one Strands agent on AgentCore over the selected domain packs',
});
