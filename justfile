# One entry point for every sample. Each recipe wraps one native command; the samples' READMEs
# show that raw command too. Contract: docs/build_a_sample.md §4.
#
# Install once:  uv tool install rust-just
# Sample keys:   cmcd · mediaconnect · medialive · hls-doctor · agentic-iops-streaming · hydrolix

set dotenv-load
set shell := ["bash", "-euo", "pipefail", "-c"]

# List recipes
default:
    @just --list --unsorted

# Check offline prerequisites; `just doctor aws` makes deployment checks strict
[group('setup')]
doctor group="":
    uv run python scripts/check_prerequisites.py {{ group }}

# Run a sample locally (MCP stdio or local agent server)
[group('develop')]
run sample *args:
    #!/usr/bin/env bash
    set -euo pipefail
    case "{{ sample }}" in
      cmcd)         uv run --package cmcd-mcp-server serve-cmcd {{ args }} ;;
      mediaconnect) uv run --package mediaconnect-mcp-server serve-mediaconnect {{ args }} ;;
      medialive)    uv run --package medialive-mcp-server serve-medialive {{ args }} ;;
      agentic-iops-streaming)          AGENTIC_IOPS_LOCAL_MODE=true uv run --package agentic-iops-streaming serve-agentic-iops-streaming {{ args }} ;;
      hls-doctor)   uv run --package hls-doctor serve-hls-doctor {{ args }} ;;
      hydrolix)     just _pending hydrolix ;;
      *)            just _unknown "{{ sample }}" ;;
    esac

# Offline tests: all, one sample, or one shared package (`contracts`, `video-quality`)
[group('develop')]
test sample="":
    #!/usr/bin/env bash
    set -euo pipefail
    case "{{ sample }}" in
      "")        uv run pytest ;;
      contracts) uv run pytest packages/media_ops_contracts/tests ;;
      video-quality) uv run pytest packages/media_ops_video_quality/tests ;;
      cmcd)      uv run pytest samples/cmcd/tests ;;
      mediaconnect) uv run pytest samples/mediaconnect/tests ;;
      medialive) uv run pytest samples/medialive/tests/scenarios samples/medialive/tests/pack ;;
      agentic-iops-streaming)       uv run pytest samples/agentic-iops-streaming/tests/contract ;;
      hls-doctor) uv run pytest samples/hls-doctor/tests ;;
      hydrolix)  uv run pytest scripts/tests/test_*hydrolix*.py ;;
      *)         just _unknown "{{ sample }}" ;;
    esac

# The tests that start real processes (MCP servers, a hung server the deadline must kill)
[group('develop')]
test-slow:
    uv run pytest -m slow

# Lint and format check
[group('develop')]
lint:
    uv run ruff check .
    uv run ruff format --check .

# Static type check (ratchet list in pyproject.toml [tool.mypy])
[group('develop')]
typecheck:
    uv run mypy

# Replay fixture scenarios and score them
[group('develop')]
eval:
    uv run pytest -m eval

# The agent on a recorded incident with a scripted model: no AWS account, no Bedrock
[group('develop')]
demo:
    uv run --package agentic-iops-streaming demo-agentic-iops-streaming

# Start every converted MCP server on fixtures, or probe live read paths with `just smoke aws`
[group('develop')]
smoke target="":
    #!/usr/bin/env bash
    set -euo pipefail
    case "{{ target }}" in
      "")  uv run python scripts/smoke_demo_servers.py ;;
      aws) uv run python scripts/smoke_aws_servers.py ;;
      *)   echo "Unknown smoke target '{{ target }}'. Use: aws" >&2; exit 1 ;;
    esac

# Check README structure, relative links and model-ID consistency
[group('develop')]
docs-check:
    uv run python scripts/check_readme_structure.py
    uv run python scripts/check_repository_layout.py
    uv run python scripts/check_public_hygiene.py
    uv run python scripts/check_docs_claims.py
    uv run python scripts/check_model_ids.py

# Remove caches, eval output, bytecode, cdk.out and CDK tsc output, and an old release's leftovers (keeps .venv, node_modules and .env)
[group('develop')]
clean:
    uv run python scripts/clean_local_state.py

# `just clean`, plus every node_modules (reinstall with npm ci)
[group('develop')]
clean-all:
    uv run python scripts/clean_local_state.py --all

# Deploy a sample with its existing deploy material (scripts/confirm_aws_action.py asks first; --yes skips)
[group('deploy')]
deploy sample *flags:
    #!/usr/bin/env bash
    set -euo pipefail
    case "{{ sample }}" in
      cmcd)     uv run python scripts/manage_cmcd_stack.py deploy {{ flags }} ;;
      hydrolix) uv run python scripts/manage_hydrolix_stack.py deploy {{ flags }} ;;
      agentic-iops-streaming)      uv run python scripts/manage_agentic_iops_streaming_stack.py deploy {{ flags }} ;;
      medialive|mediaconnect) echo "{{ sample }} deploys as a domain pack of agentic-iops-streaming: set MEDIA_DOMAINS, then just deploy agentic-iops-streaming" >&2; exit 1 ;;
      *) just _unknown "{{ sample }}" ;;
    esac

# Create or reuse the CMCD bucket-read token through an active Systems Manager tunnel
[group('deploy')]
cmcd-token *flags:
    uv run python scripts/manage_cmcd_stack.py create-read-token {{ flags }}

# Verify the root .env CMCD token can read and is forbidden from writing
[group('deploy')]
cmcd-token-verify:
    uv run python scripts/verify_influxdb_read_token.py

# Remove everything `just deploy <sample>` created (scripts/confirm_aws_action.py asks first; --yes skips)
[group('deploy')]
destroy sample *flags:
    #!/usr/bin/env bash
    set -euo pipefail
    case "{{ sample }}" in
      cmcd)     uv run python scripts/manage_cmcd_stack.py destroy {{ flags }} ;;
      hydrolix) uv run python scripts/manage_hydrolix_stack.py destroy {{ flags }} ;;
      agentic-iops-streaming)      uv run python scripts/manage_agentic_iops_streaming_stack.py destroy {{ flags }} ;;
      medialive|mediaconnect) echo "{{ sample }} deploys as a domain pack of agentic-iops-streaming: set MEDIA_DOMAINS, then just destroy agentic-iops-streaming" >&2; exit 1 ;;
      *) just _unknown "{{ sample }}" ;;
    esac

[private]
_pending sample step="":
    @echo "'{{ sample }}' uses separate runtime and web-app processes; follow samples/{{ sample }}/README.md." >&2; exit 1

[private]
_unknown sample:
    @echo "Unknown sample '{{ sample }}'. Use: cmcd mediaconnect medialive hls-doctor agentic-iops-streaming hydrolix" >&2; exit 1
