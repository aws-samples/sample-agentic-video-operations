"""Classify user intent and determine routing."""

import json
from langchain.chat_models import init_chat_model
from langchain_core.messages import SystemMessage, HumanMessage
from shared.observability import traced_node
from shared.config import Settings
from coordinator.prompts import CLASSIFY_PROMPT


@traced_node("coordinator.classify", "coordinator", "classifier")
def classify_node(state: dict) -> dict:
    """Classify the user's request into domain, intent, and urgency."""
    settings = Settings()
    llm = init_chat_model(
        settings.agent_model_id,
        model_provider="bedrock_converse",
        region_name=settings.region,
    )

    user_message = state["messages"][-1].content

    response = llm.invoke([
        SystemMessage(content=CLASSIFY_PROMPT),
        HumanMessage(content=user_message),
    ])

    try:
        classification = json.loads(response.content)
    except json.JSONDecodeError:
        classification = {
            "domain": "both",
            "intent": user_message[:100],
            "urgency": "medium",
            "is_destructive": False,
            "is_simple": False,
        }

    return {"classification": classification}


def classify_router(state: dict) -> str:
    """Route based on classification: fast_path for simple queries, plan for complex."""
    classification = state.get("classification", {})
    if classification.get("is_simple", False):
        return "fast_path"
    return "needs_planning"
