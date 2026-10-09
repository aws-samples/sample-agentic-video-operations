"""Everything agentic-iops-streaming builds once at startup: packs, tools, skills, prompt, model.

Only these are shared across requests; the agent itself is built per request
(extend_agentic_iops_streaming.md §1). A broken pack or skill stops startup, not a request.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from strands.models import BedrockModel, Model
from strands.models.model import CacheConfig
from strands.types.tools import AgentTool

from agentic_iops_streaming.bootstrap.build_workflow_store import build_workflow_store
from agentic_iops_streaming.bootstrap.create_load_skill_tool import create_load_skill_tool
from agentic_iops_streaming.bootstrap.create_workflow_tools import (
    WorkflowTools,
    create_workflow_tools,
)
from agentic_iops_streaming.bootstrap.wrap_pack_tools import (
    ToolSurface,
    claim_tool_name,
    wrap_pack_tools,
)
from agentic_iops_streaming.bootstrap.wrap_workflow_tools import wrap_workflow_tools
from agentic_iops_streaming.prompts.build_system_prompt import build_system_prompt
from agentic_iops_streaming.settings.runtime_settings import AgenticIopsSettings
from media_ops_contracts.domain_pack import DomainPack, load_domain_packs, parse_domain_names
from media_ops_contracts.resolve_approval_signing_key import resolve_approval_signing_key
from media_ops_contracts.skill_catalogue import SkillCatalogue

AGENTIC_IOPS_SKILLS = Path(__file__).parents[1] / "skills"
COORDINATOR = "coordinator"  # the owner of the workflow tools, for tool-name clashes


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
    workflow_tools: WorkflowTools | None = None,
) -> AgenticIops:
    """Build once at startup. `workflow_tools` overrides the coordinator's own tools.

    The override is for tests and evals, which pass the clock, store, discovery policy and
    workflow id suffix of their run, and may wrap the write to observe it. It still honours
    ALLOW_WORKFLOW_DISCOVERY through `create_workflow_tools`.
    """
    if packs is None:
        packs = load_domain_packs(parse_domain_names(settings.media_domains))
    surface = wrap_pack_tools(list(packs), allow_writes=settings.allow_writes)
    signing_key = resolve_approval_signing_key(settings.approval_signing_key)
    if workflow_tools is None:
        workflow_tools = create_workflow_tools(
            settings, build_workflow_store(settings), signing_key=signing_key
        )
    add_workflow_tools(surface, workflow_tools)
    skill_paths = [*sorted(AGENTIC_IOPS_SKILLS.glob("*/SKILL.md"))]
    skill_paths += [path for pack in packs for path in pack.skill_paths]
    catalogue = SkillCatalogue.from_paths(skill_paths)
    return AgenticIops(
        settings=settings,
        surface=surface,
        tools=[*surface.tools, create_load_skill_tool(catalogue)],
        system_prompt=build_system_prompt(catalogue),
        model=model or create_bedrock_model(settings),
        signing_key=signing_key,
    )


def add_workflow_tools(surface: ToolSurface, workflow_tools: WorkflowTools) -> None:
    """The coordinator's own tools join the one surface, so `save_workflow` reaches the §4 hook.

    Their names are claimed like a pack's, under `coordinator`, so a pack offering `get_workflow`
    stops startup rather than quietly shadowing this one.
    """
    if workflow_tools.is_empty:
        return
    for function in workflow_tools.reads:
        claim_tool_name(surface.pack_by_tool, function.__name__, COORDINATOR)
    for write in workflow_tools.writes:
        claim_tool_name(surface.pack_by_tool, write.function.__name__, COORDINATOR)
        surface.writes[write.function.__name__] = write
    surface.tools.extend(wrap_workflow_tools(workflow_tools))


def create_bedrock_model(settings: AgenticIopsSettings) -> BedrockModel:
    """The agent's model, caching its stable prefix.

    Every model call in a turn re-sends the same tool schemas and system prompt, about 4.1K
    tokens per call. Cache points after the tools, the system prompt and the last user
    message let Bedrock read them from its prompt cache instead ("auto" places them only for
    models that support caching). `usage_reported` shows the cache reads and writes.
    """
    if not settings.agent_model_id:
        raise RuntimeError("AGENT_MODEL_ID is not set. Set it in the root .env or the CDK stack.")
    return BedrockModel(
        model_id=settings.agent_model_id,
        region_name=settings.aws_region,
        cache_config=CacheConfig(strategy="auto", tools_ttl=True),
    )
