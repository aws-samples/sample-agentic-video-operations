# Walkthrough: Fixtures → Local → Deployed

One path through the repository, in order of commitment. Each stage says what it
costs before you start it. You can stop after any stage and still have seen
something real.

| Stage | What runs | AWS account | Cost |
|---|---|---|---|
| [0 — Prove it works](#stage-0--prove-it-works) | Every MCP server, on recorded incidents | Not needed | $0 |
| [1 — Investigate with your AI client](#stage-1--investigate-an-incident-with-your-ai-client) | One sample in your MCP client, on fixtures | Not needed | Your client's model usage |
| [2 — Run the hub agent locally](#stage-2--run-the-hub-agent-locally) | The Strands hub on your machine; media data stays fixtures | Bedrock only | Cents per question |
| [3 — Deploy](#stage-3--deploy) | A sample's full stack in your account | Yes | Real, per sample README |

## Stage 0 — Prove it works

*No AWS account, no credentials, no `.env`, no cost.*

```bash
git clone https://github.com/aws-samples/sample-agentic-video-operations.git
cd sample-agentic-video-operations
uv tool install rust-just
just smoke
```

Expected output:

```text
ok   cmcd             analyze_buffer_events
ok   mediaconnect     list_flows
ok   medialive        list_channels
Demo smoke passed without AWS clients.
```

What just happened: each converted sample started as a real MCP server over
stdio and answered a read tool from **fixtures** — recorded AWS API responses
for a scripted incident, stored in [`fixtures/`](../fixtures/). `DEMO=1` makes
every AWS client a replay client ([`create_aws_client.py`](../packages/media_ops_contracts/src/media_ops_contracts/create_aws_client.py)),
so nothing can call AWS even if credentials are present. Each sample has a
default scenario (for example `input_loss` for MediaLive, `srt_packet_loss` for
MediaConnect); `DEMO_SCENARIO` selects another one from `fixtures/`.

## Stage 1 — Investigate an incident with your AI client

*No AWS account. The model is the one your MCP client already uses.*

Register a sample as an MCP server in Claude Code, Claude Desktop, Amazon Q
CLI, Kiro, or any MCP client. Replace `/path/to/repo` with your absolute clone
path — the `--justfile` flag makes the config work from any directory:

```json
{
  "mcpServers": {
    "medialive-demo": {
      "command": "just",
      "args": ["--justfile", "/path/to/repo/justfile", "run", "medialive"],
      "env": { "DEMO": "1" }
    }
  }
}
```

Then ask your client:

> Any problems with my MediaLive channels?

The agent lists the fixture channels, finds the `input_loss` incident on the
demo channel, reads its metrics and alerts, and explains the failure — a full
diagnosis loop with zero AWS footprint. Swap `medialive` for `mediaconnect`
(an SRT packet-loss scenario) or `cmcd` (viewer buffering analytics) in the
`args` to investigate the other domains.

The thumbnail tools are the one exception at this stage: vision analysis needs
a Bedrock model, so they return a clear error in demo mode without one.

## Stage 2 — Run the hub agent locally

*Bedrock is the only AWS service touched; media data is still fixtures.
A diagnosis question costs cents (token usage of one agent turn).*

The hub is one Strands agent that loads the samples as domain packs and pauses
every write for operator approval. Give it a model and credentials, keep the
media side in demo mode:

```bash
cp .env.example .env          # defaults: DEMO=false, writes disabled
just doctor aws               # credentials, Bedrock access
DEMO=1 just run hub           # local mode on port 8080
```

In another terminal:

```bash
curl -N -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Any problems with my channels?"}'
```

The response streams one JSON event per SSE `data:` line — `task_started`,
`tool_called` per tool, then `final_answer` — the same `StreamEvent` contract a
deployed hub emits ([`extend_the_hub.md`](extend_the_hub.md)). Writes stay off unless you
set `ALLOW_WRITES=true`, and even then every write pauses for an explicit
approval decision.

## Stage 3 — Deploy

*Creates billable resources in your account. Each sample README states what
runs, what it costs while idle, and its exact verification request.*

```bash
just doctor aws
just deploy <key>      # prints account and region, asks for confirmation
```

Follow the "Verify the deployment" section of that sample's README, then tear
down when done:

```bash
just destroy <key>
```

Confirm the CloudFormation stacks are gone afterwards — orphaned media
infrastructure keeps billing while idle.

## Troubleshooting

- **`just: command not found`** — `uv tool install rust-just`, then reopen the
  shell so `~/.local/bin` is on `PATH`.
- **`just smoke` cannot find `uv`** — install [uv](https://docs.astral.sh/uv/)
  first; it provides Python 3.12+ automatically from `.python-version`.
- **The MCP client shows no tools** — the `--justfile` path must be absolute,
  and `"env"` must include `"DEMO": "1"` for a credential-free run.
- **A tool answers with an AWS credentials error** — `DEMO` is not set in that
  process: the server is talking to real AWS. Stop it and set `DEMO=1`.
- **The first Stage 2 request fails with `AGENT_MODEL_ID is not set`** — create
  the root `.env` (`cp .env.example .env`); the defaults fill it in.
- **Stage 2 model errors** — your account needs access to the models in the
  root `.env` (`just doctor aws` checks); see the README "Models" section.
