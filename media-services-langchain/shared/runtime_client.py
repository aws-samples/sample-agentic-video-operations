"""Client for invoking sibling AgentCore runtimes."""

import json
import boto3
from botocore.config import Config


class AgentCoreRuntimeClient:
    """Invoke EML/EMX runtimes from the coordinator."""

    def __init__(self, region: str = "us-west-2"):
        self._client = boto3.client(
            "bedrock-agentcore",
            region_name=region,
            config=Config(
                read_timeout=300,
                connect_timeout=10,
                retries={"max_attempts": 2},
            ),
        )

    def invoke(self, runtime_arn: str, task: dict, session_id: str) -> str:
        """Invoke a specialist runtime with a delegated task.

        Args:
            runtime_arn: ARN of the target runtime (EML or EMX)
            task: TodoItem dict with task_id + description
            session_id: Session ID for runtime session pinning

        Returns:
            Response text from the specialist agent.
        """
        payload_dict = {
            "prompt": task["description"],
            "task_id": task["task_id"],
            "stream": False,
        }
        payload_bytes = json.dumps(payload_dict).encode("utf-8")

        response = self._client.invoke_agent_runtime(
            agentRuntimeArn=runtime_arn,
            runtimeSessionId=session_id,
            payload=payload_bytes,
        )

        # Response body is a streaming blob — read all chunks
        chunks = []
        body = response.get("body") or response.get("response")
        if body:
            if hasattr(body, "read"):
                raw = body.read()
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                for line in raw.strip().split("\n"):
                    line = line.strip()
                    if line.startswith("data: "):
                        line = line[6:]
                    if line:
                        try:
                            parsed = json.loads(line)
                            if isinstance(parsed, dict):
                                if "data" in parsed:
                                    chunks.append(parsed["data"])
                                elif "response" in parsed:
                                    chunks.append(parsed["response"])
                            elif isinstance(parsed, str):
                                chunks.append(parsed)
                        except json.JSONDecodeError:
                            chunks.append(line)
            elif hasattr(body, "iter_lines"):
                for line in body.iter_lines():
                    if line:
                        line_str = line.decode("utf-8") if isinstance(line, bytes) else line
                        if line_str.startswith("data: "):
                            line_str = line_str[6:]
                        try:
                            parsed = json.loads(line_str)
                            if isinstance(parsed, dict) and "data" in parsed:
                                chunks.append(parsed["data"])
                        except json.JSONDecodeError:
                            chunks.append(line_str)

        return "".join(chunks) if chunks else "No response from specialist."
