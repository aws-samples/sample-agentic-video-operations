"""
AgentCore Memory Utilities

This module provides utility functions for retrieving and formatting conversation
messages from Bedrock Agent Core memory system.
"""

import logging
from typing import Literal

from bedrock_agentcore.memory import MemoryClient
from strands.types.content import Message

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agentcore-memory-utils")


def get_agentcore_memory_messages(
    memory_id: str,
    actor_id: str,
    session_id: str,
    last_k_turns: int = 20,
) -> list[Message]:
    """
    Retrieve conversation messages from AgentCore memory and format them.

    This function retrieves the specified number of conversation turns from memory
    and formats them in the standard message format with role and content structure.

    Args:
        memory_id: ID of the memory resource
        actor_id: ID of the user/actor
        session_id: ID of the current conversation session
        last_k_turns: Number of conversation turns to retrieve from history (default: 20)

    Returns:
        List of formatted messages in the format:
        [
            {"role": "user", "content": [{"text": "Hello, my name is Strands!"}]},
            {"role": "assistant", "content": [{"text": "Hi there! How can I help you today?"}]}
        ]

    Raises:
        Exception: If there's an error retrieving messages from memory
    """
    try:
        # Initialize memory client
        memory_client = MemoryClient()
        recent_turns = memory_client.get_last_k_turns(
            memory_id=memory_id,
            actor_id=actor_id,
            session_id=session_id,
            k=last_k_turns,
        )

        formatted_messages: list[Message] = []

        for turn in recent_turns or []:
            for message in turn:
                # Extract role and content from the memory format
                raw_role = message.get("role", "user")

                # Normalize role to lowercase to match Bedrock Converse API requirements
                role = raw_role.lower() if isinstance(raw_role, str) else "user"

                if role not in ["user", "assistant"]:
                    role = "user"

                # Handle different content formats
                content_text = ""
                if "content" in message:
                    if isinstance(message["content"], dict) and "text" in message["content"]:
                        content_text = message["content"]["text"]
                    elif isinstance(message["content"], str):
                        content_text = message["content"]
                    elif isinstance(message["content"], list):
                        # Handle list of content items
                        for content_item in message["content"]:
                            if isinstance(content_item, dict) and "text" in content_item:
                                content_text = content_item["text"]
                                break
                            elif isinstance(content_item, str):
                                content_text = content_item
                                break

                # Skip messages with empty content
                if not content_text.strip():
                    continue

                # Format message in the required structure
                speaker: Literal["user", "assistant"] = (
                    "assistant" if role == "assistant" else "user"
                )
                formatted_message: Message = {
                    "role": speaker,
                    "content": [{"text": content_text}],
                }

                formatted_messages.append(formatted_message)
        # Metadata only (RB10): no message text, no actor or session id.
        turns = len(recent_turns or [])
        print(f"🧠 Memory: {len(formatted_messages)} messages from {turns} turns")
        # Return messages in inverted order (most recent first)
        return formatted_messages[::-1]

    except Exception as e:
        logger.error("Memory read failed: %s", type(e).__name__)
        raise Exception(f"Failed to retrieve messages from AgentCore memory: {str(e)}") from e
