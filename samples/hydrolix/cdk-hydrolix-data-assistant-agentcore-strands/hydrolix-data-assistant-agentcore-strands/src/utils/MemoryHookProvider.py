"""
Memory Hook Provider for Bedrock Agent Core

This module provides a hook provider for Bedrock Agent Core that manages conversation
memory. It handles loading recent conversation history when the agent starts and
saving new messages as they are added to the conversation.

The MemoryHookProvider class integrates with the Bedrock Agent Core memory system
to provide persistent conversation history across sessions.
"""

import logging
from typing import Any

from bedrock_agentcore.memory import MemoryClient
from strands.hooks.events import MessageAddedEvent
from strands.hooks.registry import HookProvider, HookRegistry

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("personal-agent")


class MemoryHookProvider(HookProvider):
    """
    Hook provider for managing conversation memory in Bedrock Agent Core.

    This class provides hooks for loading conversation history when the agent
    initializes and saving messages as they are added to the conversation.

    Attributes:
        memory_id: ID of the memory resource
        actor_id: ID of the user/actor
        session_id: ID of the current conversation session
        last_k_turns: Number of conversation turns to retrieve from history
    """

    def __init__(
        self,
        memory_id: str,
        actor_id: str,
        session_id: str,
        last_k_turns: int = 20,
    ):
        """
        Initialize the memory hook provider.

        Args:
            memory_id: ID of the memory resource
            actor_id: ID of the user/actor
            session_id: ID of the current conversation session
            last_k_turns: Number of conversation turns to retrieve from history (default: 20)
        """
        self.memory_client = MemoryClient()
        self.memory_id = memory_id
        self.actor_id = actor_id
        self.session_id = session_id
        self.last_k_turns = last_k_turns

    def on_message_added(self, event: MessageAddedEvent):
        """
        Store messages in memory as they are added to the conversation.

        This method saves each new message to the Bedrock Agent Core memory system
        for future reference.

        Args:
            event: Message added event
        """
        messages = event.agent.messages
        try:
            last_message = messages[-1]
            role = last_message.get("role")
            content = last_message.get("content") or []
            # The first text block is what is saved; tool blocks are not.
            content_to_save = next((item["text"] for item in content if "text" in item), None)
            if not role or not content_to_save:
                print(f"💾 Memory: nothing to save ({len(messages)} messages in the turn)")
                return
            self.memory_client.save_conversation(
                memory_id=self.memory_id,
                actor_id=self.actor_id,
                session_id=self.session_id,
                messages=[(content_to_save, role)],
            )
            # Metadata only (RB10): no message text, no actor or session id.
            print(f"💾 Memory: saved one {role} message (length={len(content_to_save)})")
        except Exception as error:
            print(f"💥 Memory save failed: {type(error).__name__}")
            logger.error("Memory save failed: %s", type(error).__name__)

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        """
        Register memory hooks with the hook registry.

        Args:
            registry: Hook registry to register with
        """
        # Register memory hooks
        registry.add_callback(MessageAddedEvent, self.on_message_added)
