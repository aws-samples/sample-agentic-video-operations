"""Content quality monitoring for MediaConnect"""
from typing import Dict, Any, List
from .base import BaseMonitor


class ContentQualityMonitor(BaseMonitor):
    """Monitor content quality metrics"""

    def get_metrics_list(self) -> List[str]:
        """Content quality metrics from AWS documentation"""
        return [
            'AudioStreamMissing',
            'BlackFramesBreaching',
            'FrozenFramesBreaching',
            'SilentAudioBreaching',
            'TimecodePresent',
            'VideoStreamMissing',
        ]

    def get_metric_units(self) -> Dict[str, str]:
        """Content quality metric units"""
        return {
            'AudioStreamMissing': 'Count',
            'BlackFramesBreaching': 'Count',
            'FrozenFramesBreaching': 'Count',
            'SilentAudioBreaching': 'Count',
            'TimecodePresent': 'Count',
            'VideoStreamMissing': 'Count',
        }

    def _analyze_health(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze content quality"""
        score = 100
        issues = []

        stream_issues = ['AudioStreamMissing', 'VideoStreamMissing']
        for stream_metric in stream_issues:
            if metrics.get(stream_metric, {}).get('datapoints'):
                if any(dp.get('Sum', 0) > 0 for dp in metrics[stream_metric]['datapoints']):
                    score -= 40
                    issues.append(f"{stream_metric} detected")

        quality_issues = ['BlackFramesBreaching', 'FrozenFramesBreaching', 'SilentAudioBreaching']
        for quality_metric in quality_issues:
            if metrics.get(quality_metric, {}).get('datapoints'):
                if any(dp.get('Sum', 0) > 0 for dp in metrics[quality_metric]['datapoints']):
                    score -= 15
                    issues.append(f"{quality_metric} detected")

        return {
            'score': max(0, score),
            'status': 'EXCELLENT' if score >= 90 else 'GOOD' if score >= 70 else 'POOR',
            'issues': issues
        }
