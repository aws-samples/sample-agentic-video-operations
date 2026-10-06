# Media ops hub CDK app

Deploys the hub to Amazon Bedrock AgentCore: the runtime, its memory, the approval
signing-key secret and an IAM role built from each selected pack's
`samples/<key>/iam_permissions.json`. Use `just deploy hub` and `just destroy hub` from
the repository root; they pass the root `.env` settings as context and parameters:

| Root `.env` | CDK |
|---|---|
| `MEDIA_DOMAINS` (default `medialive,mediaconnect`) | `-c mediaDomains=...` |
| `ALLOW_WRITES=true` | `-c allowWrites=true` (grants the packs' `write` statements) |
| `AGENT_MODEL_ID`, `THUMBNAIL_MODEL_ID` | `--parameters BedrockModelId=...`, `ThumbnailModelId=...` |

Offline checks: `npm ci`, `npm test`, `npx cdk synth --quiet`.
