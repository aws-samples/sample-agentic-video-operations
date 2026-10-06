"""
Hydrolix Time-Series Data Analyst Subagent

This subagent handles all Hydrolix time-series data analysis tasks including:
- SQL query generation and execution against Hydrolix using ClickHouse dialect
- Streaming video analytics and diagnostics
- Time-series data interpretation and insights
"""

from strands import tool

from src.settings.runtime_settings import load_runtime_settings
from src.tools.run_hydrolix_subagent import run_hydrolix_subagent
from src.utils import get_request_context, load_file_content


def _load_hydrolix_system_prompt(user_timezone: str = "US/Pacific") -> str:
    """Load the system prompt for Hydrolix time-series analysis."""
    fallback_prompt = (
        "You are a specialized Hydrolix Time-Series Data Analyst with expertise in "
        "analyzing streaming video analytics, CDN performance, and time-series diagnostics. "
        "You can execute SQL queries using ClickHouse dialect, interpret time-series data, "
        "and provide actionable insights."
    )

    try:
        hydrolix_table = load_runtime_settings().hydrolix_table

        prompt = load_file_content(
            "src/tools/hydrolix_agent_instructions.txt", default_content=fallback_prompt
        )
        # Replace both timezone and table name placeholders
        prompt = prompt.replace("{timezone}", user_timezone)
        prompt = prompt.replace("{hydrolix_table}", hydrolix_table)
        return prompt
    except Exception:
        return fallback_prompt.replace("{timezone}", user_timezone)


@tool
def hydrolix_agent(query: str) -> str:
    """
    Analyze Hydrolix time-series data based on user questions.

    This subagent specializes in time-series data analysis using Hydrolix, including:
    - Streaming video analytics and CDN performance
    - CMCD (Common Media Client Data) metrics analysis
    - Buffer starvation and playback quality diagnostics
    - Regional and edge performance comparisons

    Args:
        query: User question about time-series data that needs to be analyzed

    Returns:
        str: Time-series data analysis results and insights
    """
    print(f"📊 HYDROLIX TIME-SERIES ANALYST SUBAGENT (query length={len(query)})")
    system_prompt = _load_hydrolix_system_prompt(get_request_context().user_timezone)
    question = f"Analyze time-series data for this user question: {query}"
    return run_hydrolix_subagent("hydrolix_agent", system_prompt, question)
