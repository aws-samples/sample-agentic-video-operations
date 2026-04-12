"""conftest.py — stub heavy third-party packages so unit tests can import src.*
without installing strands, bedrock_agentcore, etc.
"""
import types
import sys
from unittest.mock import MagicMock


def _make_module(name: str, attrs: dict | None = None) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__path__ = []
    mod.__package__ = name
    if attrs:
        for k, v in attrs.items():
            setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


# Strands — Agent, tool decorator, BedrockModel
_tool_decorator = lambda fn=None, **kw: fn if fn else (lambda f: f)
_make_module("strands", {"tool": _tool_decorator, "Agent": MagicMock()})
_make_module("strands.models", {"BedrockModel": MagicMock()})
_make_module("strands.tools")
_make_module("strands.tools.mcp", {"MCPClient": MagicMock()})

# bedrock_agentcore — full module hierarchy needed by code_interpreter
_make_module("bedrock_agentcore")
_make_module("bedrock_agentcore.runtime")
_make_module("bedrock_agentcore.runtime.server", {"AgentServer": MagicMock()})
_make_module("bedrock_agentcore.tools")
_make_module("bedrock_agentcore.tools.code_interpreter_client", {"CodeInterpreter": MagicMock()})
