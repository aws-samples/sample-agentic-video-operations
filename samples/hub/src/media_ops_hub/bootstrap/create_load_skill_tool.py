"""The one tool that reads a skill body on demand (extend_the_hub.md §3)."""

from strands import tool
from strands.types.tools import AgentTool

from media_ops_contracts.skill_catalogue import SkillCatalogue


def create_load_skill_tool(catalogue: SkillCatalogue) -> AgentTool:
    @tool
    def load_skill(name: str) -> str:
        """Load the steps of one skill listed in the system prompt, by its name."""
        return catalogue.load_body(name)

    return load_skill
