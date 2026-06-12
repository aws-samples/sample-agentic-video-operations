"""Coordinator LangGraph state machine (advanced variant).

Flow: classify → plan (write_todos) → approve → route → merge → respond

This is the structured StateGraph variant with explicit nodes for each phase.
The deployed entrypoint (coordinator/main.py) uses a simpler ReAct tool-calling
approach. This graph is used by unit tests and serves as a reference for the
full write_todos deep-agent pattern.

Reference: langchain-ai/langchain-aws samples/memory/agentcore_memory_checkpointer.ipynb
"""

from langgraph.graph import StateGraph, START, END
from langgraph_checkpoint_aws import AgentCoreMemorySaver
from shared.state import CoordinatorState
from coordinator.nodes.classify import classify_node, classify_router
from coordinator.nodes.plan import plan_node
from coordinator.nodes.approve import approve_node, approval_router
from coordinator.nodes.route import route_node
from coordinator.nodes.merge import merge_node, merge_router
from coordinator.nodes.respond import respond_node


def build_coordinator_graph(checkpointer: AgentCoreMemorySaver):
    """Build and compile the coordinator graph."""
    graph = StateGraph(CoordinatorState)

    graph.add_node("classify", classify_node)
    graph.add_node("plan", plan_node)
    graph.add_node("approve", approve_node)
    graph.add_node("route", route_node)
    graph.add_node("merge", merge_node)
    graph.add_node("respond", respond_node)

    graph.add_edge(START, "classify")
    graph.add_conditional_edges("classify", classify_router, {
        "fast_path": "respond",
        "needs_planning": "plan",
    })
    graph.add_edge("plan", "approve")
    graph.add_conditional_edges("approve", approval_router, {
        "approved": "route",
        "rejected": "respond",
    })
    graph.add_edge("route", "merge")
    graph.add_conditional_edges("merge", merge_router, {
        "all_complete": "respond",
        "pending": "route",
    })
    graph.add_edge("respond", END)

    return graph.compile(checkpointer=checkpointer)
