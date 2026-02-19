"""
Memory Hook Provider for Bedrock Agent Core

This module provides a hook provider for Bedrock Agent Core that manages conversation
memory. It handles loading recent conversation history when the agent starts and
saving new messages as they are added to the conversation.

The MemoryHookProvider class integrates with the Bedrock Agent Core memory system
to provide persistent conversation history across sessions.
"""

import logging

from strands.hooks.events import MessageAddedEvent
from strands.hooks.registry import HookProvider, HookRegistry
from bedrock_agentcore.memory import MemoryClient

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

        print("\n" + "=" * 70)
        print("💾 MEMORY HOOK - MESSAGE ADDED EVENT")
        print("=" * 70)
        print("📨 AGENT MESSAGES:")
        print("-" * 70)

        # Display all messages in a formatted way
        for idx, msg in enumerate(messages, 1):
            role = msg.get("role", "unknown")
            role_icon = (
                "🤖" if role == "assistant" else "👤" if role == "user" else "❓"
            )
            print(f"  {idx}. {role_icon} {role.upper()}:")

            if "content" in msg and msg["content"]:
                for content_idx, content_item in enumerate(msg["content"], 1):
                    if "text" in content_item:
                        text_preview = (
                            content_item["text"][:150] + "..."
                            if len(content_item["text"]) > 150
                            else content_item["text"]
                        )
                        print(f"     📝 Text: {text_preview}")
                    elif "toolResult" in content_item:
                        print(
                            f"     🔧 Tool Result: {content_item['toolResult'].get('toolUseId', 'N/A')}"
                        )

        print("-" * 70)

        try:
            last_message = messages[-1]

            print("🔍 PROCESSING LAST MESSAGE:")
            print(f"   📋 Role: {last_message.get('role', 'unknown')}")
            print(f"   📊 Content items: {len(last_message.get('content', []))}")

            # Check if the message has the expected structure
            if (
                "role" in last_message
                and "content" in last_message
                and last_message["content"]
            ):
                role = last_message["role"]

                # Look for text content or specific toolResult content
                content_to_save = None

                print("   🔎 Searching for saveable content...")

                for content_idx, content_item in enumerate(last_message["content"], 1):
                    print(
                        f"      Content item {content_idx}: {list(content_item.keys())}"
                    )

                    # Check for regular text content
                    if "text" in content_item:
                        content_to_save = content_item["text"]
                        print(
                            f"      ✅ Found text content (length: {len(content_to_save)})"
                        )
                        break

                if content_to_save:
                    print("\n" + "=" * 50)
                    print("💾 SAVING TO MEMORY")
                    print("=" * 50)
                    print(
                        f"📝 Content preview: {content_to_save[:200]}{'...' if len(content_to_save) > 200 else ''}"
                    )
                    print(f"👤 Role: {role}")
                    print(f"🆔 Memory ID: {self.memory_id}")
                    print(f"👤 Actor ID: {self.actor_id}")
                    print(f"🔗 Session ID: {self.session_id}")
                    print("=" * 50)

                    self.memory_client.save_conversation(
                        memory_id=self.memory_id,
                        actor_id=self.actor_id,
                        session_id=self.session_id,
                        messages=[(content_to_save, role)],
                    )
                    print("✅ SUCCESSFULLY SAVED TO MEMORY")

            else:
                print("❌ INVALID MESSAGE STRUCTURE")
                print("   Missing required fields: role, content, or content is empty")

        except Exception as e:
            print(f"💥 MEMORY SAVE ERROR: {str(e)}")
            logger.error(f"Memory save error: {e}")

        print("=" * 70 + "\n")

    def register_hooks(self, registry: HookRegistry):
        """
        Register memory hooks with the hook registry.

        Args:
            registry: Hook registry to register with
        """
        # Register memory hooks
        registry.add_callback(MessageAddedEvent, self.on_message_added)
