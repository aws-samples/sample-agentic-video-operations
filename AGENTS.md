# Agentic Video Operations Contributor Guide

This repository contains AWS samples for investigating and operating live-video
workflows with AI agents. Use the root `justfile` for every common command.

## Samples

| Key | Folder | Operator outcome | Common commands |
|---|---|---|---|
| `cmcd` | [`samples/cmcd/`](samples/cmcd/) | Investigate viewer QoE from CMCD data | `just run cmcd` · `just test cmcd` · `just deploy cmcd` |
| `mediaconnect` | [`samples/mediaconnect/`](samples/mediaconnect/) | Inspect MediaConnect transport health | `just run mediaconnect` · `just test mediaconnect` |
| `medialive` | [`samples/medialive/`](samples/medialive/) | Inspect MediaLive channel health | `just run medialive` · `just test medialive` · deploys through `agentic-iops-streaming` |
| `agentic-iops-streaming` | [`samples/agentic-iops-streaming/`](samples/agentic-iops-streaming/) | Investigate across MediaConnect and MediaLive; writes need approval | `just demo` · `just run agentic-iops-streaming` · `just test agentic-iops-streaming` · `just deploy agentic-iops-streaming` |
| `hydrolix` | [`samples/hydrolix/`](samples/hydrolix/) | Explore CDN and streaming analytics in a web UI | `just deploy hydrolix` · `just destroy hydrolix` |

## Read Before Editing

Read these sources in order:

1. [`build_a_sample.md`](docs/build_a_sample.md)
2. [`write_safe_tools.md`](docs/write_safe_tools.md)
3. [`extend_agentic_iops_streaming.md`](docs/extend_agentic_iops_streaming.md)
4. [`follow_development_guidelines.md`](docs/follow_development_guidelines.md)
5. [`CLAUDE.md`](.claude/CLAUDE.md)

The first three win where they differ from the guidelines. Security and
operational safety win over both.

## Five Common Tasks

1. Check the workstation before changing anything: `just doctor`
2. Run one sample locally: `just run <key>`
3. Run one sample's offline tests: `just test <key>`
4. Replay the cross-service demo without AWS: `just demo`
5. Run the quality gate: `just lint && just typecheck && just test && just eval && just docs-check`

Run `just` with no arguments to list all recipes. Deployments create billable
AWS resources; use `just destroy <key>` when finished.
`just eval` replays the agentic-iops-streaming scenarios offline and is part of the gate.
For changed deploy material, also run `cdk synth` or `cfn-lint`, as applicable.

## Change Rules

- Keep each change small and limited to its assigned files.
- Use action-oriented file and function names.
- Never commit `.env`, credentials, account IDs, ARNs, or real resource IDs.
- Keep write tools disabled unless `ALLOW_WRITES=true`.
- Every operational write requires approval and post-action verification.
- Tests and demos run offline. Live AWS probes use the explicit `just smoke aws` command.
