# agentic-iops-streaming CDK app

Deploys agentic-iops-streaming to Amazon Bedrock AgentCore: the runtime, its memory, the approval
signing-key secret and an IAM role built from each selected pack's
`samples/<key>/iam_permissions.json`. Use `just deploy agentic-iops-streaming` and `just destroy agentic-iops-streaming` from
the repository root; they pass the root `.env` settings as context and parameters:

| Root `.env` | CDK |
|---|---|
| `MEDIA_DOMAINS` (default `medialive,mediaconnect`) | `-c mediaDomains=...` |
| `ALLOW_WRITES=true` | `-c allowWrites=true` (grants the packs' `write` statements) |
| `AGENTIC_IOPS_WRITE_TAG=Key=Value` | `-c writeTag=Key=Value` (requires that resource tag on every write) |
| `AGENT_MODEL_ID` | `-c agentModelId=...` (default `us.anthropic.claude-sonnet-4-6`) |
| `THUMBNAIL_MODEL_ID` | `-c thumbnailModelId=...` (default `us.anthropic.claude-haiku-4-5-20251001-v1:0`) |

**Bedrock scope:** the runtime role may invoke only these two models. For a cross-Region
inference profile (`us.`, `eu.`, `apac.`, `global.` …) it gets the profile in this account
and region and the foundation model behind it in any region
(`arn:aws:bedrock:*::foundation-model/<model>`), because the profile routes to that model in
each of its destination regions; a bare model id gets only its foundation-model ARN. The
stack derives the foundation model from the id, so a profile can't be paired with another
model. The agent model is granted to the runtime itself; the vision model replaces the
`{vision_model}` placeholder in a pack's `samples/<key>/iam_permissions.json`. A model id
that isn't a model or profile id (`*`, `/`, an ARN) fails synth. The models are context, not
parameters, so `cdk diff` with the same `-c` options shows the exact IAM the deploy creates.

Offline checks: `npm ci`, `npm test`, `npx cdk synth --quiet`.
