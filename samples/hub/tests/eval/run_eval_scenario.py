"""Run one fixture-backed hub scenario and score its contract expectations."""

import functools
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from unittest.mock import patch

from scenario_models import ActionVerification, EvalResult, EvalScenario
from scripted_eval_model import ScriptedEvalModel
from strands.agent.agent_result import AgentResult

from hls_doctor.domain_pack import create_domain_pack as create_hls_pack
from media_ops_contracts.domain_pack import DomainPack, ReadTool, WriteTool
from media_ops_contracts.stream_event import StreamEvent
from media_ops_hub.bootstrap.create_hub import create_hub
from media_ops_hub.domain.hub_request import ApprovalDecision, HubRequest
from media_ops_hub.settings.runtime_settings import HubSettings
from media_ops_hub.workflows.run_hub_turn import stream_hub_turn
from mediaconnect_mcp.domain_pack import create_domain_pack as create_mediaconnect_pack
from medialive_mcp.domain_pack import create_domain_pack as create_medialive_pack

ROOT = Path(__file__).resolve().parents[4]


class PackFactory(Protocol):
    def __call__(self, *, clock: Callable[[], datetime]) -> DomainPack: ...


FACTORIES: dict[str, PackFactory] = {
    "medialive": create_medialive_pack,
    "mediaconnect": create_mediaconnect_pack,
    "hls": create_hls_pack,
}


@dataclass
class EvalClock:
    now: datetime = datetime(2026, 10, 6, 12, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, minutes: int) -> None:
        self.now += timedelta(minutes=minutes)


@dataclass(frozen=True)
class ObservedPack:
    source: DomainPack
    writes: list[WriteTool]

    @property
    def name(self) -> str:
        return self.source.name

    @property
    def skill_paths(self) -> Sequence[Path]:
        return self.source.skill_paths

    @property
    def fixture_scenarios(self) -> Sequence[str]:
        return self.source.fixture_scenarios

    def read_tools(self) -> list[ReadTool]:
        return list(self.source.read_tools())

    def write_tools(self) -> list[WriteTool]:
        return self.writes


def observe_writes(pack: DomainPack, count: list[int]) -> ObservedPack:
    observed: list[WriteTool] = []
    for write in pack.write_tools():
        function = write.function

        @functools.wraps(function)
        def record(*args, _function=function, **kwargs):
            count[0] += 1
            return _function(*args, **kwargs)

        observed.append(WriteTool(function=record, resource_parameter=write.resource_parameter))
    return ObservedPack(pack, observed)


def run_scenario(scenario: EvalScenario, sessions: Path) -> EvalResult:
    started = time.perf_counter()
    write_count = [0]
    agent_results: list[AgentResult] = []
    skills: list[str] = []
    model_name = os.environ.get("EVAL_MODEL", "fake")
    if model_name not in {"fake", "bedrock"}:
        raise ValueError("EVAL_MODEL must be 'fake' or 'bedrock'.")
    environment = {
        "DEMO": "1",
        "DEMO_SCENARIO": scenario.fixture,
        "FIXTURES_DIR": str(ROOT / "fixtures"),
        "AWS_REGION": "us-west-2",
        "ALLOW_WRITES": str(scenario.allow_writes).lower(),
        "APPROVAL_SIGNING_KEY": "eval-only-not-a-secret",
        "MEMORY_ID": "",
    }
    with patch.dict(os.environ, environment):
        clock = EvalClock()
        packs = [
            observe_writes(FACTORIES[name](clock=clock), write_count)
            for name in scenario.media_domains
        ]
        scripted = ScriptedEvalModel(scenario.turns)
        settings = HubSettings(
            media_domains=",".join(scenario.media_domains),
            allow_writes=scenario.allow_writes,
            approval_signing_key=environment["APPROVAL_SIGNING_KEY"],
            session_dir=sessions / scenario.name,
        )
        hub = create_hub(settings, packs=packs, model=None if model_name == "bedrock" else scripted)
        events = list(
            stream_hub_turn(
                hub,
                HubRequest(prompt=scenario.prompt),
                session_id=f"eval-{scenario.name}",
                actor_id="eval-operator",
                clock=clock,
                record_result=agent_results.append,
                record_skill=skills.append,
            )
        )
        if scenario.decision:
            approvals = [event for event in events if event.type == "approval_requested"]
            approval_id = (
                approvals[0].approval_id
                if scenario.decision.approval_id == "current" and approvals
                else "approval-for-another-channel"
            )
            clock.advance(scenario.decision.advance_minutes)
            events += list(
                stream_hub_turn(
                    hub,
                    HubRequest(
                        decision=ApprovalDecision(
                            approval_id=approval_id, approve=scenario.decision.approve
                        )
                    ),
                    session_id=f"eval-{scenario.name}",
                    actor_id="eval-operator",
                    clock=clock,
                    record_result=agent_results.append,
                    record_skill=skills.append,
                )
            )
    return score_scenario(
        scenario,
        events,
        skills,
        agent_results,
        write_count[0],
        model_name,
        (time.perf_counter() - started) * 1000,
    )


def score_scenario(
    scenario: EvalScenario,
    events: list[StreamEvent],
    skills: list[str],
    results: list[AgentResult],
    writes: int,
    model_name: str,
    latency_ms: float,
) -> EvalResult:
    tools = [event.tool for event in events if event.type == "tool_called"]
    specialists = [event.specialist for event in events if event.type == "task_started"]
    actions = {
        event.approval_id: event.action for event in events if event.type == "action_completed"
    }
    verifications = [
        ActionVerification(
            action=actions.get(event.approval_id, "unknown"),
            before_state=event.before_state,
            after_state=event.after_state,
            verified=event.verified,
        )
        for event in events
        if event.type == "verification_completed"
    ]
    text = " ".join(
        getattr(event, "text", "") or getattr(event, "message", "") for event in events
    ).lower()
    expected = scenario.expected
    failures: list[str] = []
    for label, wanted, actual in (
        ("tool", expected.tools, tools),
        ("skill", expected.skills, skills),
        ("specialist", expected.specialists, specialists),
    ):
        missing = [item for item in wanted if item not in actual]
        if missing:
            failures.append(f"missing {label}s: {', '.join(missing)}")
    forbidden = [tool for tool in expected.forbidden_tools if tool in tools]
    if forbidden:
        failures.append(f"forbidden tools called: {', '.join(forbidden)}")
    missing_words = [word for word in expected.diagnosis_keywords if word.lower() not in text]
    if missing_words:
        failures.append(f"missing diagnosis keywords: {', '.join(missing_words)}")
    if len(tools) > expected.max_tool_calls:
        failures.append(f"{len(tools)} tool calls exceeds {expected.max_tool_calls}")
    if writes != expected.writes_attempted:
        failures.append(f"writes attempted: expected {expected.writes_attempted}, got {writes}")
    failed_verifications = [item for item in verifications if not item.verified]
    if failed_verifications:
        failures.append(
            "unverified actions: "
            + ", ".join(
                f"{item.action} {item.before_state}->{item.after_state}"
                for item in failed_verifications
            )
        )
    missing_verifications = [
        wanted for wanted in expected.verifications if wanted not in verifications
    ]
    if missing_verifications:
        failures.append(
            "missing verifications: "
            + ", ".join(
                f"{item.action} {item.before_state}->{item.after_state} (verified={item.verified})"
                for item in missing_verifications
            )
        )
    usage = [result.metrics.accumulated_usage for result in results]
    return EvalResult(
        scenario=scenario.name,
        passed=not failures,
        model=model_name,
        input_tokens=sum(item["inputTokens"] for item in usage),
        output_tokens=sum(item["outputTokens"] for item in usage),
        tool_calls=tools,
        skills_loaded=skills,
        specialists=list(dict.fromkeys(specialists)),
        latency_ms=round(latency_ms, 2),
        writes_attempted=writes,
        verifications=verifications,
        failures=failures,
    )
