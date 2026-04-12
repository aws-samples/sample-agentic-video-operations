"""T10-T12: Tool import tests — verify all tools import and work via live MCP."""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.tools import __all__ as tool_exports
import src.tools as tools_module


# --- T10: All 15 tool functions import from src.tools ---

class TestT10ToolImports:
    def test_all_15_exported(self):
        assert len(tool_exports) == 15, f"Expected 15 exports, got {len(tool_exports)}: {tool_exports}"

    def test_all_callable(self):
        for name in tool_exports:
            fn = getattr(tools_module, name)
            assert callable(fn), f"{name} is not callable"


# --- T11: current_time returns a string ---

class TestT11CurrentTime:
    def test_returns_string(self):
        from src.tools import current_time
        result = current_time()
        assert isinstance(result, str), f"current_time returned {type(result)}, expected str"


# --- T12: Migrated tools return strings on error (live call with bad input) ---

class TestT12ErrorReturns:
    """Call tools with invalid channel IDs — they should return error strings, not raise."""

    def test_list_channels_returns_string(self):
        from src.tools import list_channels
        result = list_channels()
        assert isinstance(result, str), f"list_channels returned {type(result)}"

    def test_describe_channel_bad_id_returns_error_string(self):
        from src.tools import describe_channel
        result = describe_channel('INVALID_CHANNEL_99999999')
        assert isinstance(result, str)
        assert 'Error' in result or 'error' in result or 'not found' in result.lower(), \
            f"Expected error message, got: {result[:200]}"
