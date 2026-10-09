"""One model-id rule for the deploy scripts and both CDK stacks.

A bad AGENT_MODEL_ID used to fail at CloudFormation's parameter check, after npm ci, the
security diff and the image build. The scripts now refuse it first, with the same rule the
stacks enforce, read from one file so the three can't drift.
"""

import json
import re
from pathlib import Path

import manage_agentic_iops_streaming_stack as stack_script
import manage_hydrolix_stack as hydrolix
import model_id_rule
import pytest
from test_manage_agentic_iops_streaming_stack import ENV as AGENTIC_IOPS_ENV
from test_manage_agentic_iops_streaming_stack import FakeRunner as AgenticIopsRunner
from test_manage_hydrolix_stack import SETTINGS as HYDROLIX_SETTINGS
from test_manage_hydrolix_stack import FakeRunner as HydrolixRunner

ROOT = Path(__file__).resolve().parents[2]
STACKS = (
    ROOT / "samples/agentic-iops-streaming/cdk/lib/agentic-iops-streaming-stack.ts",
    ROOT / "samples/hydrolix/cdk-hydrolix-data-assistant-agentcore-strands/cdklib/"
    "cdk-hydrolix-data-assistant-agentcore-strands-stack.ts",
)
GOOD = ("us.anthropic.claude-sonnet-4-6", "anthropic.claude-sonnet-4-6",
        "us-gov.meta.llama3-70b-instruct-v1:0", "meta.llama3-70b-instruct-v1:0")  # fmt: skip
BAD = ("*", "anthropic.*", "a/b", "us.anthropic", "anthropic", "us..x",
       "arn:aws:bedrock:*::foundation-model/*", "us.anthropic.claude.extra")  # fmt: skip


def test_the_pattern_is_built_from_the_prefixes_it_lists():
    rule = json.loads((ROOT / "scripts/model_id_rule.json").read_text())
    prefix = f"(?:{'|'.join(rule['profile_prefixes'])})\\."
    model = "[a-z0-9-]+\\.[A-Za-z0-9:-]+"
    assert rule["pattern"] == f"^(?:{prefix}{model}|(?!{prefix}){model})$"


@pytest.mark.parametrize("stack", STACKS, ids=["agentic-iops-streaming", "hydrolix"])
def test_each_stack_reads_the_shared_rule_and_keeps_no_copy(stack):
    source = stack.read_text()
    assert "model_id_rule.json" in source
    assert "[A-Za-z0-9:-]+" not in source and "A-Za-z0-9.:-" not in source
    assert not re.search(r"\[\s*['\"]us['\"],\s*['\"]eu['\"]", source)  # no prefix list


def test_the_rule_accepts_model_and_profile_ids_only():
    assert all(model_id_rule.MODEL_ID_PATTERN.fullmatch(good) for good in GOOD)
    assert not any(model_id_rule.MODEL_ID_PATTERN.fullmatch(bad) for bad in BAD)


@pytest.mark.parametrize("name", ["AGENT_MODEL_ID", "THUMBNAIL_MODEL_ID"])
def test_the_agentic_iops_deploy_refuses_a_bad_model_id_before_anything_runs(name, capsys):
    runner = AgenticIopsRunner()

    assert (
        stack_script.main(
            ["deploy", "--yes"], runner, environ=AGENTIC_IOPS_ENV | {name: "anthropic.*"}
        )
        == 1
    )

    assert runner.calls == []  # no account read, npm ci, diff or build
    assert f"{name}='anthropic.*' is not a Bedrock model id" in capsys.readouterr().out


def test_the_hydrolix_deploy_refuses_a_bad_model_id_before_anything_runs(capsys):
    runner = HydrolixRunner()
    settings = HYDROLIX_SETTINGS | {"AGENT_MODEL_ID": "us.anthropic"}

    assert hydrolix.deploy_stack(runner, assume_yes=True, environ=settings, ask=lambda _: "y") == 1

    assert runner.calls == []
    assert "AGENT_MODEL_ID='us.anthropic' is not a Bedrock model id" in capsys.readouterr().out
