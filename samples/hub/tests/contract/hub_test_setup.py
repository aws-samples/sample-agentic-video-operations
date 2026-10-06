"""Build a hub over the test pack and a scripted model, with a controllable clock."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from channel_test_pack import SIGNING_KEY, ChannelTestPack
from scripted_model import ScriptedModel

from media_ops_hub.bootstrap.create_hub import Hub, create_hub
from media_ops_hub.domain.hub_request import ApprovalDecision, HubRequest
from media_ops_hub.settings.runtime_settings import HubSettings
from media_ops_hub.workflows.run_hub_turn import stream_hub_turn

OPERATOR = "operator-a"
SESSION = "session-a"


@dataclass
class Clock:
    now: datetime = field(default_factory=lambda: datetime(2026, 1, 1, 12, tzinfo=UTC))

    def __call__(self) -> datetime:
        return self.now

    def advance(self, minutes: int) -> None:
        self.now += timedelta(minutes=minutes)


@dataclass
class HubUnderTest:
    hub: Hub
    pack: ChannelTestPack
    clock: Clock

    def stream(self, prompt: str, *, session: str = SESSION, actor: str = OPERATOR):
        return stream_hub_turn(
            self.hub, HubRequest(prompt=prompt), session_id=session, actor_id=actor,
            clock=self.clock,
        )  # fmt: skip

    def ask(self, prompt: str, *, session: str = SESSION, actor: str = OPERATOR) -> list:
        return list(self.stream(prompt, session=session, actor=actor))

    def decide(
        self, approval_id: str, approve: bool, *, session: str = SESSION, actor: str = OPERATOR
    ) -> list:
        request = HubRequest(decision=ApprovalDecision(approval_id=approval_id, approve=approve))
        return list(
            stream_hub_turn(
                self.hub, request, session_id=session, actor_id=actor, clock=self.clock
            )
        )


def build_hub(
    tmp_path: Path,
    model: ScriptedModel,
    *,
    allow_writes: bool = True,
    budget: int = 12,
    local_mode: bool = False,
) -> HubUnderTest:
    clock = Clock()
    pack = ChannelTestPack(now=clock)
    settings = HubSettings(
        allow_writes=allow_writes,
        approval_signing_key=SIGNING_KEY,
        hub_tool_budget=budget,
        session_dir=tmp_path,
        hub_local_mode=local_mode,
    )
    return HubUnderTest(create_hub(settings, packs=[pack], model=model), pack, clock)


def types(events: list) -> list[str]:
    return [event.type for event in events]


def only(events: list, event_type: str):
    [event] = [event for event in events if event.type == event_type]
    return event
