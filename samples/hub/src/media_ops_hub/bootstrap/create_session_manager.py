"""Where a session's messages, agent.state and pending interrupts live between requests.

Both stores key a session by (actor, session), so an operator who reuses another's session
id reaches only their own history and pending approvals.
"""

import hashlib

from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig
from bedrock_agentcore.memory.integrations.strands.session_manager import (
    AgentCoreMemorySessionManager,
)
from strands.session import FileSessionManager, SessionManager

from media_ops_hub.settings.runtime_settings import HubSettings


def create_session_manager(settings: HubSettings, session_id: str, actor_id: str) -> SessionManager:
    """AgentCore Memory when MEMORY_ID is set (deployed); local files otherwise."""
    if settings.memory_id:
        config = AgentCoreMemoryConfig(
            memory_id=settings.memory_id, session_id=session_id, actor_id=actor_id
        )
        return AgentCoreMemorySessionManager(config, region_name=settings.aws_region)
    return FileSessionManager(
        session_id=session_id, storage_dir=actor_directory(settings, actor_id)
    )


def actor_directory(settings: HubSettings, actor_id: str) -> str:
    """One directory per actor, named by a hash: an actor id (an unverified header in IAM
    mode) never becomes a path, so it can't reach outside session_dir."""
    digest = hashlib.sha256(actor_id.encode()).hexdigest()[:32]
    return str(settings.session_dir / f"actor_{digest}")
