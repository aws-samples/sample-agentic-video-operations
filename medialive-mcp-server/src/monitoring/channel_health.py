"""Channel health monitoring for MediaLive"""
from typing import Dict, Any, List
from .base import BaseMonitor


class ChannelHealthMonitor(BaseMonitor):
    """Monitor channel-level health metrics"""

    def get_metrics_list(self) -> List[str]:
        """Channel health metrics from AWS documentation"""
        return [
            'ActiveAlerts',
            'PipelinesLocked',
            'InputVideoAligned',
            'FillMsec',
            'InputVideoFrameRate',
            'DroppedFrames',      # Uses Pipeline+Region dimensions, may return empty datapoints
            'SvqTime',            # Uses Pipeline+Region dimensions, may return empty datapoints
        ]

    def get_metric_units(self) -> Dict[str, str]:
        """Channel health metric units"""
        return {
            'ActiveAlerts': 'Count',
            'PipelinesLocked': 'Count',
            'InputVideoAligned': 'Count',
            'FillMsec': 'Milliseconds',
            'InputVideoFrameRate': 'Count',
            'DroppedFrames': 'Count',
            'SvqTime': 'Milliseconds',
        }

    def _analyze_health(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze channel health"""
        score = 100
        issues = []

        # ActiveAlerts > 0 is a significant concern
        if metrics.get('ActiveAlerts', {}).get('datapoints'):
            total_alerts = sum(dp.get('Average', 0) for dp in metrics['ActiveAlerts']['datapoints'])
            if total_alerts > 0:
                score -= 30
                issues.append(f"ActiveAlerts: {total_alerts}")

        # DroppedFrames > 0 indicates frame loss
        if metrics.get('DroppedFrames', {}).get('datapoints'):
            total_drops = sum(dp.get('Average', 0) for dp in metrics['DroppedFrames']['datapoints'])
            if total_drops > 0:
                score -= 20
                issues.append(f"DroppedFrames: {total_drops}")

        # High FillMsec indicates content fill (no source content)
        if metrics.get('FillMsec', {}).get('datapoints'):
            datapoints = metrics['FillMsec']['datapoints']
            if datapoints:
                avg_fill = sum(dp.get('Average', 0) for dp in datapoints) / len(datapoints)
                if avg_fill > 100:
                    score -= 15
                    issues.append(f"High FillMsec average: {avg_fill:.1f}ms")

        # PipelinesLocked showing unlocked state (any Average < 1)
        if metrics.get('PipelinesLocked', {}).get('datapoints'):
            for dp in metrics['PipelinesLocked']['datapoints']:
                if dp.get('Average', 1) < 1:
                    score -= 10
                    issues.append("PipelinesLocked: pipeline unlocked detected")
                    break

        return {
            'score': max(0, score),
            'status': 'EXCELLENT' if score >= 90 else 'GOOD' if score >= 70 else 'POOR',
            'issues': issues
        }
