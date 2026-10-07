"""Send one prompt or approval decision to the deployed agent and print its events.

uv run python scripts/invoke_agentic_iops_streaming.py --actor <you> "Is channel 1234567 healthy?"
uv run python scripts/invoke_agentic_iops_streaming.py --actor <you> --session <id> --approve
<approval_id>

IAM-authorized runtime (the default): the runtime refuses a request without an actor, and the AWS
CLI cannot send the custom actor header, so this adds it with a boto3 event hook.
JWT-authorized runtime (stack output InboundAuth=jwt): this posts with AGENTIC_IOPS_BEARER_TOKEN
instead,
and the actor is the token's `sub`, so --actor is not used. boto3 cannot send bearer tokens.
AWS_REGION and AGENTIC_IOPS_BEARER_TOKEN come from the root .env; the token is never an argument.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable, Iterable, Sequence
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from read_root_env import describe_root_env, load_root_env

STACK = "AgenticIopsStreamingStack"
ACTOR_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actor-Id"
SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"


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


def invoke_agentic_iops_streaming(
    arguments: argparse.Namespace,
    create_client: Callable[..., Any] = boto3.client,
    open_url: Callable[..., Any] = urllib.request.urlopen,
) -> int:
    region = os.environ.get("AWS_REGION", "")
    if not region:
        print(f"Missing AWS_REGION: not set in the environment or in {describe_root_env()}.")
        return 1
    try:
        return send(arguments, region, create_client, open_url)
    except urllib.error.HTTPError as error:
        print(f"The runtime refused the call: HTTP {error.code} {error.reason}")
        print(
            "A 401 or 403 means AGENTIC_IOPS_BEARER_TOKEN is missing, expired or from another "
            "client."
        )
    except urllib.error.URLError as error:
        print(f"The runtime could not be reached: {error.reason}")
    except (BotoCoreError, ClientError) as error:
        print(f"The runtime call failed: {error}")
        print(
            "Check the deployment (just deploy agentic-iops-streaming) and that your role may "
            "invoke it."
        )
    except (KeyError, ValueError) as error:
        print(f"Stack {STACK} or the runtime response is not what this script expects: {error!r}")
        print("Redeploy with `just deploy agentic-iops-streaming`, then retry.")
    return 1


def send(
    arguments: argparse.Namespace,
    region: str,
    create_client: Callable[..., Any],
    open_url: Callable[..., Any],
) -> int:
    outputs = read_stack_outputs(create_client("cloudformation", region_name=region))
    jwt_mode = outputs.get("InboundAuth") == "jwt"
    token = os.environ.get("AGENTIC_IOPS_BEARER_TOKEN", "").strip()
    if jwt_mode and not token:
        print(
            "This runtime takes bearer tokens: set AGENTIC_IOPS_BEARER_TOKEN to a current access "
            "token."
        )
        return 1
    if not jwt_mode and not arguments.actor:
        print("This runtime is IAM-authorized: pass --actor <your operator id>.")
        return 1
    session_id = arguments.session or f"agentic-iops-{uuid.uuid4().hex}{uuid.uuid4().hex[:4]}"
    print(f"session: {session_id}")
    payload = json.dumps(build_payload(arguments)).encode()
    if jwt_mode:
        request = build_bearer_request(region, outputs, session_id, payload, token)
        with open_url(request) as response:
            for event in read_events(response):
                print(json.dumps(event))
        return 0
    agentcore = create_client("bedrock-agentcore", region_name=region)
    add_actor_header(agentcore, arguments.actor)
    response = agentcore.invoke_agent_runtime(
        agentRuntimeArn=outputs["AgentRuntimeArn"],
        qualifier=outputs["AgentEndpointName"],
        runtimeSessionId=session_id,
        payload=payload,
        contentType="application/json",
    )
    for event in read_events(response["response"].iter_lines()):
        print(json.dumps(event))
    return 0


def build_bearer_request(
    region: str, outputs: dict[str, str], session_id: str, payload: bytes, token: str
) -> urllib.request.Request:
    """The HTTPS InvokeAgentRuntime call with OAuth instead of SigV4."""
    arn = urllib.parse.quote(outputs["AgentRuntimeArn"], safe="")
    qualifier = urllib.parse.quote(outputs["AgentEndpointName"], safe="")
    url = f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{arn}/invocations?qualifier={qualifier}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        SESSION_HEADER: session_id,
    }
    return urllib.request.Request(url, data=payload, headers=headers, method="POST")


def parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )  # noqa: E501
    parser.add_argument("prompt", nargs="?", help="the question to ask")
    parser.add_argument(
        "--actor", help="your operator id on an IAM-authorized runtime; approvals are per actor"
    )
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
    load_root_env(os.environ)
    sys.exit(invoke_agentic_iops_streaming(parse_arguments(sys.argv[1:])))
