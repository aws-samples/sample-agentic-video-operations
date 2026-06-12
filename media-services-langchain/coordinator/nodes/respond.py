"""Synthesize final response from agent results."""

import json
from langchain.chat_models import init_chat_model
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from shared.observability import traced_node
from shared.config import Settings
from coordinator.prompts import RESPOND_PROMPT


@traced_node("coordinator.respond", "coordinator", "responder")
def respond_node(state: dict) -> dict:
    """Merge all specialist results into a unified response."""
    settings = Settings()
    llm = init_chat_model(
        settings.agent_model_id,
        model_provider="bedrock_converse",
        region_name=settings.region,
    )

    user_message = state["messages"][-1].content
    agent_results = state.get("agent_results", [])

    if not agent_results:
        response = llm.invoke([
            SystemMessage(content=RESPOND_PROMPT),
            HumanMessage(content=f"Answer this directly: {user_message}"),
        ])
        return {"messages": [AIMessage(content=response.content)]}

    results_text = "\n\n".join(
        f"[{r['agent'].upper()} - {r['task_id']}]\n{r['result']}"
        for r in agent_results
    )

    response = llm.invoke([
        SystemMessage(content=RESPOND_PROMPT),
        HumanMessage(
            content=f"User request: {user_message}\n\n"
                    f"Specialist results:\n{results_text}"
        ),
    ])

    return {"messages": [AIMessage(content=response.content)]}
