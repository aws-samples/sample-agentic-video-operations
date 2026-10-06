"""A framework-free domain pack over an in-memory channel, for hub contract tests."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from media_ops_contracts.action_result import ActionResult
from media_ops_contracts.approved_action import ApprovedAction
from media_ops_contracts.domain_pack import ReadTool, WriteTool
from media_ops_contracts.require_action_approval import require_action_approval

RAW_OUTPUT_MARKER = "raw-output-never-streamed"
SIGNING_KEY = "hub-contract-test-key"


class ChannelView(BaseModel):
    channel_id: str
    state: str
    note: str = RAW_OUTPUT_MARKER


class ChannelTestPack:
    name = "testlive"
    skill_paths: list[Path] = []
    fixture_scenarios: list[str] = []

    def __init__(self, now: Callable[[], datetime]) -> None:
        self.now = now
        self.states = {"ch-1": "RUNNING"}
        self.approvals: list[ApprovedAction] = []

    def read_tools(self) -> list[ReadTool]:
        def describe_channel(channel_id: str) -> ChannelView:
            """Describe one channel."""
            return ChannelView(channel_id=channel_id, state=self.states.get(channel_id, "UNKNOWN"))

        return [describe_channel]

    def write_tools(self) -> list[WriteTool]:
        def stop_channel(
            channel_id: str, approved_action: ApprovedAction, reason: str = "maintenance"
        ) -> ActionResult:
            """Stop one channel. Needs operator approval."""
            require_action_approval(
                approved_action,
                action="stop_channel",
                resource_id=channel_id,
                signing_key=SIGNING_KEY.encode(),
                now=self.now(),
            )
            before, self.states[channel_id] = self.states[channel_id], "IDLE"
            self.approvals.append(approved_action)
            return ActionResult(
                approval_id=approved_action.approval_id,
                action="stop_channel",
                resource_id=channel_id,
                before_state=before,
                after_state=self.states[channel_id],
                verified=True,
            )

        return [WriteTool(function=stop_channel, resource_parameter="channel_id")]
