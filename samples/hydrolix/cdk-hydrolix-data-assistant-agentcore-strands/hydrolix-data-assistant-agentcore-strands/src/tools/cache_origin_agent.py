"""
Cache & Origin Performance Analysis Subagent

This subagent specializes in CDN cache efficiency and origin server performance including:
- Cache hit/miss analysis
- Origin vs edge timing comparisons
- Error rate analysis by status code
- Bandwidth and byte cost analysis
- Edge location performance breakdown
"""

from strands import tool

from src.settings.runtime_settings import load_runtime_settings
from src.tools.run_hydrolix_subagent import run_hydrolix_subagent
from src.utils import get_request_context, load_file_content


def _load_cache_origin_system_prompt(user_timezone: str = "US/Pacific") -> str:
    """Load the system prompt for cache and origin performance analysis."""
    fallback_prompt = (
        "You are a specialized CDN Cache & Origin Performance Analyst with expertise in "
        "analyzing cache efficiency, origin server performance, and content delivery "
        "optimization. You can execute SQL queries using ClickHouse dialect and provide "
        "actionable CDN insights."
    )

    try:
        hydrolix_table = load_runtime_settings().hydrolix_table

        prompt = load_file_content(
            "src/tools/cache_origin_instructions.txt", default_content=fallback_prompt
        )
        # Replace both timezone and table name placeholders
        prompt = prompt.replace("{timezone}", user_timezone)
        prompt = prompt.replace("{hydrolix_table}", hydrolix_table)
        return prompt
    except Exception:
        return fallback_prompt.replace("{timezone}", user_timezone)


@tool
def cache_origin_agent(query: str) -> str:
    """
    Analyze CDN cache efficiency and origin server performance.

    This subagent specializes in cache and origin analysis, including:
    - Cache hit/miss rates and efficiency metrics
    - Origin vs edge timing comparisons (TTFB, TTLB)
    - HTTP error rate analysis by status code
    - Bandwidth and byte cost analysis
    - Edge location (POP) performance breakdown
    - Content type caching patterns

    This data comes from CDN access logs directly (not player telemetry),
    so it has near-100% fill rates and high reliability.

    Args:
        query: User question about cache performance or origin metrics

    Returns:
        str: Cache and origin performance analysis results
    """
    print(f"🗄️ CACHE & ORIGIN PERFORMANCE SUBAGENT (query length={len(query)})")
    system_prompt = _load_cache_origin_system_prompt(get_request_context().user_timezone)
    question = f"Analyze cache and origin performance for: {query}"
    return run_hydrolix_subagent("cache_origin_agent", system_prompt, question)
