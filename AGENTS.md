# Agentic Video Operations Contributor Guide

This repository contains AWS samples for investigating and operating live-video
workflows with AI agents. Use the root `justfile` for every common command.

## Samples

| Key | Folder | Operator outcome | Common commands |
|---|---|---|---|
| `cmcd` | [`cmcd-mcp-server/`](cmcd-mcp-server/) | Investigate viewer QoE from CMCD data | `just run cmcd` · `just test cmcd` · `just deploy cmcd` |
| `mediaconnect` | [`mediaconnect-mcp-server/`](mediaconnect-mcp-server/) | Inspect MediaConnect transport health | `just run mediaconnect` · `just test mediaconnect` |
| `medialive` | [`medialive-mcp-server/`](medialive-mcp-server/) | Inspect MediaLive channel health | `just run medialive` · `just test medialive` · `just deploy medialive` |
| `langchain` | [`media-services-langchain/`](media-services-langchain/) | Coordinate MediaConnect and MediaLive specialists | `just run langchain` · `just test langchain` · `just deploy langchain` |
| `hydrolix` | [`hydrolix-cdn-insights/`](hydrolix-cdn-insights/) | Explore CDN and streaming analytics in a web UI | `just deploy hydrolix` · `just destroy hydrolix` |

## Read Before Editing

Read these sources in order:

1. [`collaboration-contract.md`](.claude/contracts/collaboration-contract.md)
2. [`sample-contract.md`](.claude/contracts/sample-contract.md)
3. [`tool-contract.md`](.claude/contracts/tool-contract.md)
4. [`agent-contract.md`](.claude/contracts/agent-contract.md)
5. [`DEVELOPMENT_GUIDELINES.md`](.claude/DEVELOPMENT_GUIDELINES.md)
6. [`CLAUDE.md`](.claude/CLAUDE.md)

The contracts win where they differ from the guidelines. Security and
operational safety win over both.

## Five Common Tasks

1. Check the workstation before changing anything: `just doctor`
2. Run one sample locally: `just run <key>`
3. Run one sample's offline tests: `just test <key>`
4. Replay the cross-service demo without AWS: `just demo`
5. Run the quality gate: `just lint && just test && just eval && just docs-check`

Run `just` with no arguments to list all recipes. Deployments create billable
AWS resources; use `just destroy <key>` when finished.
For changed deploy material, also run `cdk synth` or `cfn-lint`, as applicable.

## Change Rules

- Keep each change small and limited to its assigned files.
- Use action-oriented file and function names.
- Never commit `.env`, credentials, account IDs, ARNs, or real resource IDs.
- Keep write tools disabled unless `ALLOW_WRITES=true`.
- Every operational write requires approval and post-action verification.
- Tests and demos must run offline unless explicitly labeled as integration.
