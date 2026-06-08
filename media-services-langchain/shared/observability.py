"""OpenTelemetry instrumentation for LangGraph nodes.

Span names per the requirements:
- coordinator.route, coordinator.delegate
- eml.execute, emx.execute
- agent.memory.read, agent.memory.write

Attributes on all spans:
- agent.name, agent.role, runtime.name
- session.id, trace.id, delegated.task.id
"""

from contextlib import contextmanager
from functools import wraps
from opentelemetry import trace

tracer = trace.get_tracer("media-services-langchain")


def traced_node(span_name: str, agent_name: str, agent_role: str):
    """Decorator that wraps a LangGraph node function with an OTEL span."""
    def decorator(func):
        @wraps(func)
        def wrapper(state, *args, **kwargs):
            attributes = {
                "agent.name": agent_name,
                "agent.role": agent_role,
                "runtime.name": f"{agent_name}-runtime",
                "session.id": state.get("session_id", ""),
                "trace.id": state.get("trace_id", ""),
            }
            with tracer.start_as_current_span(span_name, attributes=attributes):
                return func(state, *args, **kwargs)
        return wrapper
    return decorator


@contextmanager
def trace_memory_op(operation: str, agent_name: str):
    """Context manager for memory read/write spans."""
    span_name = f"agent.memory.{'read' if 'read' in operation else 'write'}"
    with tracer.start_as_current_span(
        span_name,
        attributes={"agent.name": agent_name, "memory.operation": operation},
    ):
        yield


@contextmanager
def trace_delegation(task_id: str, target_agent: str):
    """Context manager for coordinator.delegate spans."""
    with tracer.start_as_current_span(
        "coordinator.delegate",
        attributes={
            "agent.name": "coordinator",
            "agent.role": "delegator",
            "delegated.task.id": task_id,
            "target.agent": target_agent,
        },
    ):
        yield
