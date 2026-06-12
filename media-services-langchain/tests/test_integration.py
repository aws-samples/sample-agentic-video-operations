"""Integration tests for deployed AgentCore runtimes.

Requires:
  - Active AWS credentials (AWS_PROFILE or env vars)
  - Deployed stack (cdk deploy)
  - .env file with runtime ARNs

Run:
  cd media-services-langchain
  python -m pytest tests/test_integration.py -v --timeout=300
"""

import json
import os
import uuid

import boto3
import pytest
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

REGION = os.getenv("AWS_REGION", "us-west-2")
COORDINATOR_ARN = os.getenv("COORDINATOR_ARN")
EML_RUNTIME_ARN = os.getenv("EML_RUNTIME_ARN")
EMX_RUNTIME_ARN = os.getenv("EMX_RUNTIME_ARN")


def _invoke(runtime_arn: str, prompt: str, session_id: str = None) -> str:
    """Invoke an AgentCore runtime and return the response text."""
    client = boto3.client("bedrock-agentcore", region_name=REGION)
    session_id = session_id or f"integration-test-{uuid.uuid4()}"
    payload = json.dumps({"prompt": prompt}).encode("utf-8")

    response = client.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn,
        runtimeSessionId=session_id,
        payload=payload,
    )

    body = response["response"].read().decode("utf-8")
    for line in body.strip().split("\n"):
        if line.startswith("data: "):
            line = line[6:]
        try:
            parsed = json.loads(line)
            if isinstance(parsed, str):
                inner = json.loads(parsed)
                if isinstance(inner, dict) and "data" in inner:
                    return inner["data"]
            elif isinstance(parsed, dict) and "data" in parsed:
                return parsed["data"]
        except (json.JSONDecodeError, TypeError):
            continue
    return body


@pytest.fixture(scope="module")
def session_id():
    return f"integration-memory-test-{uuid.uuid4()}"


def _skip_if_no_arn(arn, name):
    if not arn:
        pytest.skip(f"{name} not set in .env — deploy first")


# ============================================================
# EML Agent Tests
# ============================================================


class TestEMLAgent:
    """Direct invocation of the EML (MediaLive) specialist."""

    def test_list_channels(self):
        _skip_if_no_arn(EML_RUNTIME_ARN, "EML_RUNTIME_ARN")
        result = _invoke(EML_RUNTIME_ARN, "List all MediaLive channels")
        assert "Channel" in result or "channel" in result
        assert "RUNNING" in result or "IDLE" in result

    def test_describe_channel(self):
        _skip_if_no_arn(EML_RUNTIME_ARN, "EML_RUNTIME_ARN")
        channel_id = os.getenv("MEDIALIVE_CHANNEL_ID", "5133350")
        result = _invoke(EML_RUNTIME_ARN, f"Describe channel {channel_id}")
        assert channel_id in result or "demo-langchain" in result

    def test_health_check(self):
        """Validates Fix 5: eml_check_issues returns JSON, not dict repr."""
        _skip_if_no_arn(EML_RUNTIME_ARN, "EML_RUNTIME_ARN")
        channel_id = os.getenv("MEDIALIVE_CHANNEL_ID", "5133350")
        result = _invoke(EML_RUNTIME_ARN, f"Run a health check on channel {channel_id}")
        assert "Health" in result or "health" in result
        assert "NameError" not in result
        assert "artifact_descriptions" not in result


# ============================================================
# EMX Agent Tests
# ============================================================


class TestEMXAgent:
    """Direct invocation of the EMX (MediaConnect) specialist."""

    def test_list_flows(self):
        _skip_if_no_arn(EMX_RUNTIME_ARN, "EMX_RUNTIME_ARN")
        result = _invoke(EMX_RUNTIME_ARN, "List all MediaConnect flows")
        assert "flow" in result.lower() or "Flow" in result

    def test_describe_flow(self):
        _skip_if_no_arn(EMX_RUNTIME_ARN, "EMX_RUNTIME_ARN")
        result = _invoke(EMX_RUNTIME_ARN, "Describe the demo-srt-ingest flow")
        assert "srt" in result.lower() or "SRT" in result

    def test_flow_health(self):
        _skip_if_no_arn(EMX_RUNTIME_ARN, "EMX_RUNTIME_ARN")
        result = _invoke(EMX_RUNTIME_ARN, "Check health of the demo-srt-ingest flow")
        assert "health" in result.lower() or "Health" in result


# ============================================================
# Coordinator Tests
# ============================================================


class TestCoordinator:
    """Tests for the coordinator agent routing and response quality."""

    def test_fast_path_greeting(self):
        """Validates Fix 3: fast_path answers directly, not 'unable to gather'."""
        _skip_if_no_arn(COORDINATOR_ARN, "COORDINATOR_ARN")
        result = _invoke(COORDINATOR_ARN, "Hello, what can you help me with?")
        assert "unable to gather" not in result.lower()
        assert "wasn't able" not in result.lower()
        assert len(result) > 50

    def test_single_agent_routing_eml(self):
        _skip_if_no_arn(COORDINATOR_ARN, "COORDINATOR_ARN")
        result = _invoke(COORDINATOR_ARN, "List all MediaLive channels")
        assert "channel" in result.lower()

    def test_single_agent_routing_emx(self):
        _skip_if_no_arn(COORDINATOR_ARN, "COORDINATOR_ARN")
        result = _invoke(COORDINATOR_ARN, "List all MediaConnect flows")
        assert "flow" in result.lower()

    def test_multi_agent_routing(self):
        _skip_if_no_arn(COORDINATOR_ARN, "COORDINATOR_ARN")
        result = _invoke(
            COORDINATOR_ARN,
            "Check the full pipeline health — both MediaConnect flow and MediaLive channel",
        )
        has_eml = "MediaLive" in result or "channel" in result.lower()
        has_emx = "MediaConnect" in result or "flow" in result.lower()
        assert has_eml and has_emx, f"Expected both EML and EMX in response"

    def test_memory_store_and_recall(self, session_id):
        """Validates memory works within a session."""
        _skip_if_no_arn(COORDINATOR_ARN, "COORDINATOR_ARN")

        _invoke(
            COORDINATOR_ARN,
            "Remember: my SLA target is 99.95% and escalation goes to ops@example.com",
            session_id=session_id,
        )

        result = _invoke(
            COORDINATOR_ARN,
            "What is my SLA target?",
            session_id=session_id,
        )
        assert "99.95" in result
