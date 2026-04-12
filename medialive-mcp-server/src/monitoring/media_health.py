"""Media health monitoring for MediaLive"""
from typing import Dict, Any, List
from .base import BaseMonitor


class MediaHealthMonitor(BaseMonitor):
    """Monitor media-level health metrics (timecodes, audio levels, input errors, fill)"""

    def get_metrics_list(self) -> List[str]:
        """Media health metrics from AWS documentation"""
        return [
            'InputTimecodesPresent',
            'OutputAudioLevelDbfs',        # Also uses AudioDescriptionName dimension
            'OutputAudioLevelLkfs',        # Also uses AudioDescriptionName dimension
            'ChannelInputErrorSeconds',
            'FillMsec',
        ]

    def get_metric_units(self) -> Dict[str, str]:
        """Media health metric units"""
        return {
            'InputTimecodesPresent': 'Count',
            'OutputAudioLevelDbfs': 'Count',
            'OutputAudioLevelLkfs': 'Count',
            'ChannelInputErrorSeconds': 'Seconds',
            'FillMsec': 'Milliseconds',
        }

    def _analyze_health(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze media health"""
        score = 100
        issues = []

        # ChannelInputErrorSeconds > 0 indicates input errors
        if metrics.get('ChannelInputErrorSeconds', {}).get('datapoints'):
            total_errors = sum(dp.get('Average', 0) for dp in metrics['ChannelInputErrorSeconds']['datapoints'])
            if total_errors > 0:
                score -= 25
                issues.append(f"ChannelInputErrorSeconds: {total_errors}")

        # High FillMsec indicates content fill (no source content)
        if metrics.get('FillMsec', {}).get('datapoints'):
            datapoints = metrics['FillMsec']['datapoints']
            if datapoints:
                avg_fill = sum(dp.get('Average', 0) for dp in datapoints) / len(datapoints)
                if avg_fill > 100:
                    score -= 20
                    issues.append(f"High FillMsec average: {avg_fill:.1f}ms")

        return {
            'score': max(0, score),
            'status': 'EXCELLENT' if score >= 90 else 'GOOD' if score >= 70 else 'POOR',
            'issues': issues
        }
