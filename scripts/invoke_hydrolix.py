"""Ask the deployed Hydrolix assistant one question and print its answer.

uv run python scripts/invoke_hydrolix.py "Which CDN POP had the most 5xx errors today?"
uv run python scripts/invoke_hydrolix.py --session <id> "And yesterday?"

JWT-authorized stack (stack output InboundAuth=jwt): this posts over HTTPS with
HYDROLIX_BEARER_TOKEN, a current Cognito access token from the app's user pool; the actor
is the token's `sub`. boto3 cannot send bearer tokens. IAM-authorized stack: this calls
InvokeAgentRuntime with your AWS credentials, and the assistant runs with memory off.
AWS_REGION and HYDROLIX_BEARER_TOKEN come from the root .env; the token is never an
argument and is never printed.
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

STACK = "CdkHydrolixDataAssistantAgentcoreStrandsStack"
SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"


def read_stack_outputs(cloudformation: Any) -> dict[str, str]:
    [stack] = cloudformation.describe_stacks(StackName=STACK)["Stacks"]
    return {output["OutputKey"]: output["OutputValue"] for output in stack.get("Outputs", [])}


def read_chunks(lines: Iterable[bytes]) -> Iterable[dict[str, Any]]:
    """Each SSE `data:` line holds one JSON-encoded string, which holds one JSON object."""
    for line in lines:
        text = line.decode().strip()
        if not text.startswith("data:"):
            continue
        value = json.loads(text.removeprefix("data:").strip())
        if isinstance(value, str):
            value = json.loads(value)
        if isinstance(value, dict):
            yield value


def print_chunks(chunks: Iterable[dict[str, Any]]) -> int:
    status = 0
    for chunk in chunks:
        if "data" in chunk:
            print(chunk["data"], end="", flush=True)
        elif "notice" in chunk:
            print(f"[notice] {chunk['notice']}")
        elif "error" in chunk:
            print(f"[error] {chunk['error']}")
            status = 1
        elif "query_results" in chunk:  # this request's own queries, as they ran
            statuses = [str(query.get("status")) for query in chunk["query_results"]]
            print(f"\n[queries] {len(statuses)} ran: {', '.join(statuses) or 'none'}")
    print()
    return status


def build_bearer_request(
    region: str, outputs: dict[str, str], session_id: str, payload: bytes, token: str
) -> urllib.request.Request:
    """The HTTPS InvokeAgentRuntime call with OAuth instead of SigV4."""
    arn = urllib.parse.quote(outputs["AgentRuntimeArn"], safe="")
    qualifier = urllib.parse.quote(outputs["AgentEndpointName"], safe="")
    url = (
        f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{arn}"
        f"/invocations?qualifier={qualifier}"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        SESSION_HEADER: session_id,
    }
    return urllib.request.Request(url, data=payload, headers=headers, method="POST")


def send(
    arguments: argparse.Namespace,
    region: str,
    create_client: Callable[..., Any],
    open_url: Callable[..., Any],
) -> int:
    outputs = read_stack_outputs(create_client("cloudformation", region_name=region))
    session_id = arguments.session or f"hydrolix-{uuid.uuid4().hex}"
    print(f"session: {session_id}")
    payload = json.dumps({"prompt": arguments.prompt, "prompt_uuid": str(uuid.uuid4())}).encode()
    if outputs.get("InboundAuth") == "jwt":
        token = os.environ.get("HYDROLIX_BEARER_TOKEN", "").strip()
        if not token:
            print("This stack takes Cognito access tokens: set HYDROLIX_BEARER_TOKEN.")
            return 1
        request = build_bearer_request(region, outputs, session_id, payload, token)
        with open_url(request) as response:
            return print_chunks(read_chunks(response))
    agentcore = create_client("bedrock-agentcore", region_name=region)
    response = agentcore.invoke_agent_runtime(
        agentRuntimeArn=outputs["AgentRuntimeArn"],
        qualifier=outputs["AgentEndpointName"],
        runtimeSessionId=session_id,
        payload=payload,
        contentType="application/json",
    )
    return print_chunks(read_chunks(response["response"].iter_lines()))


def invoke_hydrolix(
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
        print(f"The assistant refused the call: HTTP {error.code} {error.reason}")
        print("A 401 or 403 means HYDROLIX_BEARER_TOKEN is missing, expired or for another app.")
    except urllib.error.URLError as error:
        print(f"The assistant could not be reached: {error.reason}")
    except (BotoCoreError, ClientError) as error:
        print(f"The call failed: {error}")
        print("Check the deployment (just deploy hydrolix) and that your role may invoke it.")
    except (KeyError, ValueError) as error:
        print(f"Stack {STACK} or the response is not what this script expects: {error!r}")
    return 1


def parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("prompt", help="the question to ask")
    parser.add_argument("--session", help="continue this session (at least 33 characters)")
    arguments = parser.parse_args(argv)
    if arguments.session and len(arguments.session) < 33:
        parser.error("AgentCore session ids are at least 33 characters long")
    return arguments


if __name__ == "__main__":
    load_root_env(os.environ)
    sys.exit(invoke_hydrolix(parse_arguments(sys.argv[1:])))
