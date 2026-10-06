"""Send one prompt or approval decision to the deployed hub and print its events.

uv run python scripts/invoke_hub.py --actor <you> "Is channel 1234567 healthy?"
uv run python scripts/invoke_hub.py --actor <you> --session <id> --approve <approval_id>

The hub refuses a request without an actor, and the AWS CLI cannot send the custom actor
header, so this adds it with a boto3 event hook. AWS_REGION comes from the root .env.
"""

import argparse
import json
import os
import sys
import uuid
from collections.abc import Callable, Iterable, Sequence
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

STACK = "MediaOpsHubStack"
ACTOR_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actor-Id"


def build_payload(arguments: argparse.Namespace) -> dict[str, Any]:
    if arguments.approve or arguments.reject:
        approval_id = arguments.approve or arguments.reject
        return {"decision": {"approval_id": approval_id, "approve": bool(arguments.approve)}}
    return {"prompt": arguments.prompt}


def read_stack_outputs(cloudformation: Any) -> dict[str, str]:
    [stack] = cloudformation.describe_stacks(StackName=STACK)["Stacks"]
    return {output["OutputKey"]: output["OutputValue"] for output in stack.get("Outputs", [])}


def add_actor_header(client: Any, actor_id: str) -> None:
    def add(request: Any, **_: Any) -> None:
        request.headers[ACTOR_HEADER] = actor_id

    client.meta.events.register("before-sign.bedrock-agentcore.InvokeAgentRuntime", add)


def read_events(lines: Iterable[bytes]) -> Iterable[dict[str, Any]]:
    """One StreamEvent per SSE `data:` line."""
    for line in lines:
        text = line.decode().strip()
        if text.startswith("data:"):
            yield json.loads(text.removeprefix("data:").strip())


def invoke_hub(
    arguments: argparse.Namespace, create_client: Callable[..., Any] = boto3.client
) -> int:
    region = os.environ.get("AWS_REGION", "")
    if not region:
        print("Missing AWS_REGION. Add it to the root .env.")
        return 1
    try:
        return send(arguments, region, create_client)
    except (BotoCoreError, ClientError) as error:
        print(f"The hub call failed: {error}")
        print("Check the deployment (just deploy hub) and that your role may invoke it.")
    except (KeyError, ValueError) as error:
        print(f"Stack {STACK} or the hub response is not what this script expects: {error!r}")
        print("Redeploy with `just deploy hub`, then retry.")
    return 1


def send(arguments: argparse.Namespace, region: str, create_client: Callable[..., Any]) -> int:
    outputs = read_stack_outputs(create_client("cloudformation", region_name=region))
    agentcore = create_client("bedrock-agentcore", region_name=region)
    add_actor_header(agentcore, arguments.actor)
    session_id = arguments.session or f"hub-{uuid.uuid4().hex}{uuid.uuid4().hex[:4]}"
    print(f"session: {session_id}")
    response = agentcore.invoke_agent_runtime(
        agentRuntimeArn=outputs["AgentRuntimeArn"],
        qualifier=outputs["AgentEndpointName"],
        runtimeSessionId=session_id,
        payload=json.dumps(build_payload(arguments)).encode(),
        contentType="application/json",
    )
    for event in read_events(response["response"].iter_lines()):
        print(json.dumps(event))
    return 0


def parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )  # noqa: E501
    parser.add_argument("prompt", nargs="?", help="the question to ask")
    parser.add_argument("--actor", required=True, help="your operator id; approvals are per actor")
    parser.add_argument("--session", help="resume this session (required for a decision)")
    decision = parser.add_mutually_exclusive_group()
    decision.add_argument("--approve", metavar="APPROVAL_ID")
    decision.add_argument("--reject", metavar="APPROVAL_ID")
    arguments = parser.parse_args(argv)
    if bool(arguments.prompt) == bool(arguments.approve or arguments.reject):
        parser.error("give a prompt, or --approve/--reject with --session")
    if (arguments.approve or arguments.reject) and not arguments.session:
        parser.error("a decision needs the --session that asked for it")
    return arguments


if __name__ == "__main__":
    sys.exit(invoke_hub(parse_arguments(sys.argv[1:])))
