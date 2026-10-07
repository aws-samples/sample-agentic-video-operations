"""Every pack write refuses inputs that differ from what the operator signed (write_safe_tools §3).

`require_action_approval` checks the action, resource, signature and expiry, never the
parameters. So each write must also call `require_signed_parameters`, or it would act on inputs
nobody approved. This sends every registered write its own inputs under an approval whose signed
parameters differ, so a new write that forgets the check fails here rather than in review.
"""

import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agentic_iops_streaming.domain.propose_write_action import propose_write_action
from media_ops_contracts.action_result import ActionResult
from media_ops_contracts.approved_action import ApprovedAction, sign_approved_action
from media_ops_contracts.domain_pack import WriteTool
from media_ops_contracts.require_action_approval import require_action_approval
from media_ops_contracts.resolve_approval_signing_key import resolve_approval_signing_key
from media_ops_contracts.tool_failure import FailureKind, ToolFailure
from mediaconnect_mcp.domain_pack import create_domain_pack as create_mediaconnect_pack
from medialive_mcp.domain_pack import create_domain_pack as create_medialive_pack

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
KEY = "contract-test-only-not-a-secret"
FIXTURES = Path(__file__).resolve().parents[4] / "fixtures"


def clock() -> datetime:
    return NOW


def pack_writes() -> list[WriteTool]:
    with pytest.MonkeyPatch.context() as environment:
        environment.setenv("DEMO", "1")  # replay clients: no call here can reach AWS
        environment.setenv("FIXTURES_DIR", str(FIXTURES))
        environment.setenv("APPROVAL_SIGNING_KEY", KEY)
        return [
            write
            for factory in (create_medialive_pack, create_mediaconnect_pack)
            for write in factory(clock=clock).write_tools()
        ]


def honest_inputs(write: WriteTool) -> dict[str, object]:
    """One value per input the model would pass; the approval is added separately."""
    inputs: dict[str, object] = {}
    for name, parameter in inspect.signature(write.function).parameters.items():
        if name == "approved_action" or parameter.default is not inspect.Parameter.empty:
            continue
        inputs[name] = 1 if parameter.annotation is int else f"demo-{name}"
    return inputs


def sign(write: WriteTool, inputs: dict[str, object], parameters: dict[str, str]) -> ApprovedAction:
    proposal = propose_write_action(write, inputs, actor_id="operator-1")
    return sign_approved_action(
        proposal.model_copy(update={"parameters": parameters}),
        approval_id="ap-1",
        expires_at=NOW + timedelta(minutes=10),
        signing_key=resolve_approval_signing_key(KEY),
    )


def tampered_approvals(write: WriteTool) -> dict[str, ApprovedAction]:
    """The honest signed parameters, with one extra and (when there are any) one changed."""
    inputs = honest_inputs(write)
    signed = propose_write_action(write, inputs, actor_id="operator-1").parameters
    tampered = {"an-extra-signed-input": sign(write, inputs, signed | {"not_an_input": "1"})}
    if signed:
        first = sorted(signed)[0]
        tampered["a-changed-signed-input"] = sign(write, inputs, signed | {first: "other"})
    return tampered


def refusal_kind(write: WriteTool, approved_action: ApprovedAction) -> FailureKind | None:
    try:
        write.function(**honest_inputs(write), approved_action=approved_action)
    except ToolFailure as failure:
        return failure.kind
    return None


CASES = [
    pytest.param(write, label, approved, id=f"{write.function.__name__}-{label}")
    for write in pack_writes()
    for label, approved in tampered_approvals(write).items()
]


def test_every_pack_write_is_covered():
    names = {write.function.__name__ for write in pack_writes()}
    assert {"stop_channel", "switch_channel_input", "delete_schedule_action", "stop_flow"} <= names
    assert {case.values[0].function.__name__ for case in CASES} == names


@pytest.mark.parametrize(("write", "label", "approved"), CASES)
def test_a_write_refuses_inputs_the_operator_did_not_sign(write, label, approved):
    assert refusal_kind(write, approved) is FailureKind.APPROVAL_REQUIRED


@pytest.mark.parametrize("write", pack_writes(), ids=lambda write: write.function.__name__)
def test_the_same_call_honestly_signed_is_not_refused_for_its_approval(write):
    """The control: the refusals above come from the parameters, not from the harness."""
    inputs = honest_inputs(write)
    honest = sign(
        write, inputs, propose_write_action(write, inputs, actor_id="operator-1").parameters
    )

    assert refusal_kind(write, honest) not in {
        FailureKind.APPROVAL_REQUIRED,
        FailureKind.APPROVAL_EXPIRED,
    }


def test_a_write_that_checks_only_the_approval_itself_is_caught():
    """The check this file exists for: a planted write that skips the parameters."""

    def switch_input_carelessly(
        channel_id: str, input_attachment: str, approved_action: ApprovedAction
    ) -> ActionResult:
        require_action_approval(
            approved_action,
            action="switch_input_carelessly",
            signing_key=resolve_approval_signing_key(KEY),
            now=NOW,
            resource_id=channel_id,
        )
        return ActionResult(
            approval_id=approved_action.approval_id,
            action="switch_input_carelessly",
            resource_id=channel_id,
            before_state="primary",
            after_state=input_attachment,
            verified=True,
        )

    careless = WriteTool(function=switch_input_carelessly, resource_parameter="channel_id")

    kinds = {
        label: refusal_kind(careless, approved)
        for label, approved in tampered_approvals(careless).items()
    }

    assert kinds == {"an-extra-signed-input": None, "a-changed-signed-input": None}
