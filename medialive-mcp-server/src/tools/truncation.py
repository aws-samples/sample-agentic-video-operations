"""Response truncation for metrics and log data.

Limits datapoint/event arrays to prevent large responses from flooding
the agent context window. Preserves first and last elements for trend
visibility and adds metadata about truncation.
"""

from typing import Any, Dict, List


def truncate_metrics_response(datapoints: List[Any], max_points: int = 20) -> Dict[str, Any]:
    """Truncate datapoint arrays, keeping first N/2 + last N-N/2 for trend visibility.

    Args:
        datapoints: List of metric datapoints.
        max_points: Maximum number of datapoints to keep.

    Returns:
        Dict with 'datapoints' (truncated list), '_truncated' (bool), '_original_count' (int).
    """
    original_count = len(datapoints)
    if original_count <= max_points:
        return {
            "datapoints": datapoints,
            "_truncated": False,
            "_original_count": original_count,
        }

    half = max_points // 2
    remainder = max_points - half
    truncated = datapoints[:half] + datapoints[-remainder:]
    return {
        "datapoints": truncated,
        "_truncated": True,
        "_original_count": original_count,
    }


def truncate_logs_response(events: List[Any], max_events: int = 20) -> Dict[str, Any]:
    """Truncate log event arrays with same first/last strategy.

    Args:
        events: List of log events.
        max_events: Maximum number of events to keep.

    Returns:
        Dict with 'events' (truncated list), '_truncated' (bool), '_original_count' (int).
    """
    original_count = len(events)
    if original_count <= max_events:
        return {
            "events": events,
            "_truncated": False,
            "_original_count": original_count,
        }

    half = max_events // 2
    remainder = max_events - half
    truncated = events[:half] + events[-remainder:]
    return {
        "events": truncated,
        "_truncated": True,
        "_original_count": original_count,
    }
