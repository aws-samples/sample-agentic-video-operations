# One entry point for every sample. Each recipe wraps one native command; the samples' READMEs
# show that raw command too. Contract: docs/build_a_sample.md §4.
#
# Install once:  uv tool install rust-just
# Sample keys:   cmcd · mediaconnect · medialive · hub · langchain · hydrolix

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
      hub)          HUB_LOCAL_MODE=true uv run --package media-ops-hub serve-hub {{ args }} ;;
      langchain)    just _pending langchain 4 ;;
      hydrolix)     just _pending hydrolix 5 ;;
      *)            just _unknown "{{ sample }}" ;;
    esac

# Offline tests: all, or one sample (`just test contracts` for packages/media_ops_contracts)
[group('develop')]
test sample="":
    #!/usr/bin/env bash
    set -euo pipefail
    case "{{ sample }}" in
      "")        uv run pytest ;;
      contracts) uv run pytest packages/media_ops_contracts/tests ;;
      cmcd)      uv run pytest samples/cmcd/tests ;;
      mediaconnect) uv run pytest samples/mediaconnect/tests ;;
      medialive) uv run pytest samples/medialive/tests/scenarios samples/medialive/tests/pack ;;
      hub)       uv run pytest samples/hub/tests/contract ;;
      hydrolix)  uv run pytest scripts/tests/test_manage_hydrolix_stack.py ;;
      langchain) just _pending "{{ sample }}" ;;
      *)         just _unknown "{{ sample }}" ;;
    esac

# Lint and format check
[group('develop')]
lint:
    uv run ruff check .
    uv run ruff format --check .

# Replay fixture scenarios and score them
[group('develop')]
eval:
    @just _pending_eval

# Coordinator on recorded incidents, no AWS account needed
[group('develop')]
demo:
    @just _pending demo 4

# Start every converted MCP server on fixtures and call one read tool
[group('develop')]
smoke:
    uv run python scripts/smoke_demo_servers.py

# Check README structure and relative links of converted samples
[group('develop')]
docs-check:
    uv run python scripts/check_readme_structure.py
    uv run python scripts/check_repository_layout.py

# Deploy a sample with its existing deploy material (scripts/confirm_aws_action.py asks first; --yes skips)
[group('deploy')]
deploy sample *flags:
    #!/usr/bin/env bash
    set -euo pipefail
    case "{{ sample }}" in
      cmcd)     uv run python scripts/manage_cmcd_stack.py deploy {{ flags }} ;;
      hydrolix) uv run python scripts/manage_hydrolix_stack.py deploy {{ flags }} ;;
      mediaconnect|medialive|langchain) just _pending "{{ sample }}" ;;
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
      mediaconnect|medialive|langchain) just _pending "{{ sample }}" ;;
      *) just _unknown "{{ sample }}" ;;
    esac

[private]
_pending sample step="":
    @echo "'{{ sample }}' is not converted yet{{ if step != '' { ' (step ' + step + ')' } else { '' } }}; see its README." >&2; exit 1

[private]
_pending_eval:
    @echo "Eval scenarios arrive with the hub in step 4." >&2; exit 1

[private]
_unknown sample:
    @echo "Unknown sample '{{ sample }}'. Use: cmcd mediaconnect medialive langchain hydrolix" >&2; exit 1
