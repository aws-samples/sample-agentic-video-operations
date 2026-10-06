"""Everything the hub builds once at startup: packs, tools, skills, prompt, model.

Only these are shared across requests; the agent itself is built per request
(extend_the_hub.md §1). A broken pack or skill stops startup, not a request.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from strands.models import BedrockModel, Model
from strands.types.tools import AgentTool

from media_ops_contracts.domain_pack import DomainPack, load_domain_packs, parse_domain_names
from media_ops_contracts.resolve_approval_signing_key import resolve_approval_signing_key
from media_ops_contracts.skill_catalogue import SkillCatalogue
from media_ops_hub.bootstrap.create_load_skill_tool import create_load_skill_tool
from media_ops_hub.bootstrap.wrap_pack_tools import ToolSurface, wrap_pack_tools
from media_ops_hub.prompts.build_system_prompt import build_system_prompt
from media_ops_hub.settings.runtime_settings import HubSettings

HUB_SKILLS = Path(__file__).parents[1] / "skills"


@dataclass(frozen=True)
class Hub:
    settings: HubSettings
    surface: ToolSurface
    tools: list[AgentTool]
    system_prompt: str
    model: Model
    signing_key: bytes


def create_hub(
    settings: HubSettings, *, packs: Sequence[DomainPack] | None = None, model: Model | None = None
) -> Hub:
    if packs is None:
        packs = load_domain_packs(parse_domain_names(settings.media_domains))
    surface = wrap_pack_tools(list(packs), allow_writes=settings.allow_writes)
    skill_paths = [*sorted(HUB_SKILLS.glob("*/SKILL.md"))]
    skill_paths += [path for pack in packs for path in pack.skill_paths]
    catalogue = SkillCatalogue.from_paths(skill_paths)
    return Hub(
        settings=settings,
        surface=surface,
        tools=[*surface.tools, create_load_skill_tool(catalogue)],
        system_prompt=build_system_prompt(catalogue),
        model=model or create_bedrock_model(settings),
        signing_key=resolve_approval_signing_key(settings.approval_signing_key),
    )


def create_bedrock_model(settings: HubSettings) -> BedrockModel:
    if not settings.agent_model_id:
        raise RuntimeError("AGENT_MODEL_ID is not set. Set it in the root .env or the CDK stack.")
    return BedrockModel(model_id=settings.agent_model_id, region_name=settings.aws_region)
