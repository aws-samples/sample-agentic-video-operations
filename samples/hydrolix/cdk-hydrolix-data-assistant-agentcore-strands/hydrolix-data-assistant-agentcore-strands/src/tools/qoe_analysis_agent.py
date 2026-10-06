"""
QoE (Quality of Experience) Analysis Subagent

This subagent specializes in streaming video Quality of Experience analysis including:
- Buffer health and starvation analysis
- Bitrate adaptation and throughput metrics
- Session-level quality tracking
- Geographic QoE breakdown
- CMCD data quality validation
"""

from strands import tool

from src.settings.runtime_settings import load_runtime_settings
from src.tools.run_hydrolix_subagent import run_hydrolix_subagent
from src.utils import get_request_context, load_file_content


def _load_qoe_system_prompt(user_timezone: str = "US/Pacific") -> str:
    """Load the system prompt for QoE analysis."""
    fallback_prompt = (
        "You are a specialized Quality of Experience (QoE) Analyst with expertise in "
        "analyzing streaming video quality metrics, buffer health, bitrate adaptation, and "
        "viewer experience. You can execute SQL queries using ClickHouse dialect and provide "
        "actionable QoE insights."
    )

    try:
        hydrolix_table = load_runtime_settings().hydrolix_table

        prompt = load_file_content(
            "src/tools/qoe_analysis_instructions.txt", default_content=fallback_prompt
        )
        # Replace both timezone and table name placeholders
        prompt = prompt.replace("{timezone}", user_timezone)
        prompt = prompt.replace("{hydrolix_table}", hydrolix_table)
        return prompt
    except Exception:
        return fallback_prompt.replace("{timezone}", user_timezone)


@tool
def qoe_analysis_agent(query: str) -> str:
    """
    Analyze streaming video Quality of Experience (QoE) metrics.

    This subagent specializes in QoE analysis using CMCD data, including:
    - Buffer health analysis (buffer length, starvation events)
    - Bitrate adaptation (encoded bitrate, throughput, top bitrate)
    - Session-level quality tracking and startup performance
    - Geographic QoE breakdown by country and edge location
    - Content segmentation analysis by type and format

    IMPORTANT: CMCD fields are player-side telemetry and may have NULL values
    if the video player doesn't implement CMCD. Always validate data quality first.

    Args:
        query: User question about streaming video quality of experience

    Returns:
        str: QoE analysis results and recommendations
    """
    print(f"📺 QoE ANALYSIS SUBAGENT (query length={len(query)})")
    system_prompt = _load_qoe_system_prompt(get_request_context().user_timezone)
    question = f"Analyze Quality of Experience for: {query}"
    return run_hydrolix_subagent("qoe_analysis_agent", system_prompt, question)
