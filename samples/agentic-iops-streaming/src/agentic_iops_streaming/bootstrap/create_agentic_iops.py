"""Everything agentic-iops-streaming builds once at startup: packs, tools, skills, prompt, model.

Only these are shared across requests; the agent itself is built per request
(extend_agentic_iops_streaming.md §1). A broken pack or skill stops startup, not a request.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from strands.models import BedrockModel, Model
from strands.types.tools import AgentTool

from agentic_iops_streaming.bootstrap.create_load_skill_tool import create_load_skill_tool
from agentic_iops_streaming.bootstrap.wrap_pack_tools import ToolSurface, wrap_pack_tools
from agentic_iops_streaming.prompts.build_system_prompt import build_system_prompt
from agentic_iops_streaming.settings.runtime_settings import AgenticIopsSettings
from media_ops_contracts.domain_pack import DomainPack, load_domain_packs, parse_domain_names
from media_ops_contracts.resolve_approval_signing_key import resolve_approval_signing_key
from media_ops_contracts.skill_catalogue import SkillCatalogue

AGENTIC_IOPS_SKILLS = Path(__file__).parents[1] / "skills"


@dataclass(frozen=True)
class AgenticIops:
    settings: AgenticIopsSettings
    surface: ToolSurface
    tools: list[AgentTool]
    system_prompt: str
    model: Model
    signing_key: bytes


def create_agentic_iops(
    settings: AgenticIopsSettings,
    *,
    packs: Sequence[DomainPack] | None = None,
    model: Model | None = None,
) -> AgenticIops:
    if packs is None:
        packs = load_domain_packs(parse_domain_names(settings.media_domains))
    surface = wrap_pack_tools(list(packs), allow_writes=settings.allow_writes)
    skill_paths = [*sorted(AGENTIC_IOPS_SKILLS.glob("*/SKILL.md"))]
    skill_paths += [path for pack in packs for path in pack.skill_paths]
    catalogue = SkillCatalogue.from_paths(skill_paths)
    return AgenticIops(
        settings=settings,
        surface=surface,
        tools=[*surface.tools, create_load_skill_tool(catalogue)],
        system_prompt=build_system_prompt(catalogue),
        model=model or create_bedrock_model(settings),
        signing_key=resolve_approval_signing_key(settings.approval_signing_key),
    )


def create_bedrock_model(settings: AgenticIopsSettings) -> BedrockModel:
    if not settings.agent_model_id:
        raise RuntimeError("AGENT_MODEL_ID is not set. Set it in the root .env or the CDK stack.")
    return BedrockModel(model_id=settings.agent_model_id, region_name=settings.aws_region)
