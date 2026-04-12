"""Output health monitoring for MediaLive"""
from typing import Dict, Any, List
from .base import BaseMonitor


class OutputHealthMonitor(BaseMonitor):
    """Monitor output-level health metrics"""

    def get_metrics_list(self) -> List[str]:
        """Output health metrics from AWS documentation"""
        return [
            'NetworkOut',
            'ActiveOutputs',              # Also uses OutputGroupName dimension
            'Output4xxErrors',             # Also uses OutputGroupName dimension
            'Output5xxErrors',             # Also uses OutputGroupName dimension
            'OutputAudioLevelDbfs',        # Also uses AudioDescriptionName dimension
            'OutputAudioLevelLkfs',        # Also uses AudioDescriptionName dimension
            'ComplexFrcPresent',
            'DroppedFrames',               # Uses Pipeline+Region dimensions, may return empty datapoints
            'SvqTime',                     # Uses Pipeline+Region dimensions, may return empty datapoints
        ]

    def get_metric_units(self) -> Dict[str, str]:
        """Output health metric units"""
        return {
            'NetworkOut': 'Megabits/Second',
            'ActiveOutputs': 'Count',
            'Output4xxErrors': 'Count',
            'Output5xxErrors': 'Count',
            'OutputAudioLevelDbfs': 'Count',
            'OutputAudioLevelLkfs': 'Count',
            'ComplexFrcPresent': 'Count',
            'DroppedFrames': 'Count',
            'SvqTime': 'Milliseconds',
        }

    def _analyze_health(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze output health"""
        score = 100
        issues = []

        # Output4xxErrors > 0 indicates client-side output errors
        if metrics.get('Output4xxErrors', {}).get('datapoints'):
            total_4xx = sum(dp.get('Average', 0) for dp in metrics['Output4xxErrors']['datapoints'])
            if total_4xx > 0:
                score -= 30
                issues.append(f"Output4xxErrors: {total_4xx}")

        # Output5xxErrors > 0 indicates server-side output errors
        if metrics.get('Output5xxErrors', {}).get('datapoints'):
            total_5xx = sum(dp.get('Average', 0) for dp in metrics['Output5xxErrors']['datapoints'])
            if total_5xx > 0:
                score -= 30
                issues.append(f"Output5xxErrors: {total_5xx}")

        # DroppedFrames > 0 indicates frame loss
        if metrics.get('DroppedFrames', {}).get('datapoints'):
            total_drops = sum(dp.get('Average', 0) for dp in metrics['DroppedFrames']['datapoints'])
            if total_drops > 0:
                score -= 20
                issues.append(f"DroppedFrames: {total_drops}")

        return {
            'score': max(0, score),
            'status': 'EXCELLENT' if score >= 90 else 'GOOD' if score >= 70 else 'POOR',
            'issues': issues
        }
