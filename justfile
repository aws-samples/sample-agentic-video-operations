# One entry point for every sample. Each recipe wraps one native command; the samples' READMEs
# show that raw command too. Contract: .claude/contracts/sample-contract.md §4.
#
# Install once:  uv tool install rust-just
# Sample keys:   cmcd · mediaconnect · medialive · langchain · hydrolix

set dotenv-load
set shell := ["bash", "-euo", "pipefail", "-c"]

# List recipes
default:
    @just --list --unsorted

# Check tools, AWS credentials, Bedrock model access and CDK bootstrap
[group('setup')]
doctor:
    uv run python scripts/check_prerequisites.py

# Run a sample locally (MCP stdio or local agent server)
[group('develop')]
run sample *args:
    #!/usr/bin/env bash
    set -euo pipefail
    case "{{ sample }}" in
      cmcd)         just _pending cmcd 1 ;;
      mediaconnect) just _pending mediaconnect 2 ;;
      medialive)    just _pending medialive 3 ;;
      langchain)    just _pending langchain 4 ;;
      hydrolix)     just _pending hydrolix 5 ;;
      *)            just _unknown "{{ sample }}" ;;
    esac

# Offline tests: all, or one sample (`just test contracts` for media_ops_contracts)
[group('develop')]
test sample="":
    #!/usr/bin/env bash
    set -euo pipefail
    case "{{ sample }}" in
      "")        uv run pytest ;;
      contracts) uv run pytest media_ops_contracts/tests ;;
      cmcd|mediaconnect|medialive|langchain|hydrolix) just _pending "{{ sample }}" ;;
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
    uv run pytest -m eval

# Coordinator on recorded incidents, no AWS account needed
[group('develop')]
demo:
    @just _pending demo 4

# Check README structure and relative links of converted samples
[group('develop')]
docs-check:
    uv run python scripts/check_readme_structure.py

# Deploy a sample with its existing deploy material (scripts/confirm_aws_action.py asks first; --yes skips)
[group('deploy')]
deploy sample *flags:
    #!/usr/bin/env bash
    set -euo pipefail
    case "{{ sample }}" in
      cmcd|mediaconnect|medialive|langchain|hydrolix) just _pending "{{ sample }}" ;;
      *) just _unknown "{{ sample }}" ;;
    esac

# Remove everything `just deploy <sample>` created (scripts/confirm_aws_action.py asks first; --yes skips)
[group('deploy')]
destroy sample *flags:
    #!/usr/bin/env bash
    set -euo pipefail
    case "{{ sample }}" in
      cmcd|mediaconnect|medialive|langchain|hydrolix) just _pending "{{ sample }}" ;;
      *) just _unknown "{{ sample }}" ;;
    esac

[private]
_pending sample step="":
    @echo "'{{ sample }}' is not converted yet{{ if step != '' { ' (step ' + step + ')' } else { '' } }}; see its README." >&2; exit 1

[private]
_unknown sample:
    @echo "Unknown sample '{{ sample }}'. Use: cmcd mediaconnect medialive langchain hydrolix" >&2; exit 1
