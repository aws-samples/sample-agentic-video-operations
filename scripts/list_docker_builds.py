"""Every Dockerfile in the repository, with the context and setup CI builds it with.

uv run python scripts/list_docker_builds.py   # prints the GitHub Actions matrix as JSON

A test fails when a tracked Dockerfile is missing here, so no image skips the build gate.
"""

import json

HYDROLIX = "samples/hydrolix/cdk-hydrolix-data-assistant-agentcore-strands"
FETCH_HYDROLIX_MCP = (
    "uv run python -c 'import sys, manage_hydrolix_stack as m; "
    "sys.exit(m.install_pinned_mcp_server(m.run_command))'"
)

DOCKER_BUILDS: list[dict[str, str]] = [
    {"dockerfile": "samples/agentic-iops-streaming/Dockerfile", "context": "."},
    {
        "dockerfile": f"{HYDROLIX}/hydrolix-data-assistant-agentcore-strands/Dockerfile",
        "context": f"{HYDROLIX}/hydrolix-data-assistant-agentcore-strands",
        # The image needs the pinned mcp_hydrolix source that `just deploy hydrolix` fetches.
        "prepare": FETCH_HYDROLIX_MCP,
    },
]


if __name__ == "__main__":
    print(json.dumps({"include": [{"prepare": "", **build} for build in DOCKER_BUILDS]}))
