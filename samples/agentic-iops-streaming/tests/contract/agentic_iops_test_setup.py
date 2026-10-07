"""Build the agent over the test pack and a scripted model, with a controllable clock."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from channel_test_pack import SIGNING_KEY, ChannelTestPack
from scripted_model import ScriptedModel

from agentic_iops_streaming.bootstrap.create_agentic_iops import AgenticIops, create_agentic_iops
from agentic_iops_streaming.domain.agentic_iops_request import AgenticIopsRequest, ApprovalDecision
from agentic_iops_streaming.settings.runtime_settings import AgenticIopsSettings
from agentic_iops_streaming.workflows.run_agentic_iops_turn import stream_agentic_iops_turn

OPERATOR = "operator-a"
SESSION = "session-a"
COSTED_MODEL_ID = "us.anthropic.claude-sonnet-4-6"


@dataclass
class Clock:
    now: datetime = field(default_factory=lambda: datetime(2026, 1, 1, 12, tzinfo=UTC))

    def __call__(self) -> datetime:
        return self.now

    def advance(self, minutes: int) -> None:
        self.now += timedelta(minutes=minutes)


@dataclass
class AgenticIopsUnderTest:
    iops: AgenticIops
    pack: ChannelTestPack
    clock: Clock

    def stream(self, prompt: str, *, session: str = SESSION, actor: str = OPERATOR):
        return stream_agentic_iops_turn(
            self.iops, AgenticIopsRequest(prompt=prompt), session_id=session, actor_id=actor,
            clock=self.clock,
        )  # fmt: skip

    def ask(self, prompt: str, *, session: str = SESSION, actor: str = OPERATOR) -> list:
        return list(self.stream(prompt, session=session, actor=actor))

    def decide(
        self, approval_id: str, approve: bool, *, session: str = SESSION, actor: str = OPERATOR
    ) -> list:
        request = AgenticIopsRequest(
            decision=ApprovalDecision(approval_id=approval_id, approve=approve)
        )
        return list(
            stream_agentic_iops_turn(
                self.iops, request, session_id=session, actor_id=actor, clock=self.clock
            )
        )


def build_agentic_iops(
    tmp_path: Path,
    model: ScriptedModel,
    *,
    allow_writes: bool = True,
    budget: int = 12,
    local_mode: bool = False,
    model_id: str | None = None,
    jwt_issuer: str = "",
    jwt_clients: str = "",
) -> AgenticIopsUnderTest:
    clock = Clock()
    pack = ChannelTestPack(now=clock)
    settings = AgenticIopsSettings(
        allow_writes=allow_writes,
        approval_signing_key=SIGNING_KEY,
        agentic_iops_tool_budget=budget,
        session_dir=tmp_path,
        agentic_iops_local_mode=local_mode,
        agent_model_id=model_id,
        agentic_iops_jwt_issuer=jwt_issuer,
        agentic_iops_jwt_allowed_clients=jwt_clients,
    )
    return AgenticIopsUnderTest(
        create_agentic_iops(settings, packs=[pack], model=model), pack, clock
    )


def types(events: list) -> list[str]:
    return [event.type for event in events]


def only(events: list, event_type: str):
    [event] = [event for event in events if event.type == event_type]
    return event
