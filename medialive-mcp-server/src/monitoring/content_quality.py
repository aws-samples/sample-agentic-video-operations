"""Content quality monitoring for MediaLive"""
from typing import Dict, Any, List
from .base import BaseMonitor


class ContentQualityMonitor(BaseMonitor):
    """Monitor content quality metrics (MQCS, black/freeze frames, continuity errors, input loss)"""

    def get_metrics_list(self) -> List[str]:
        """Content quality metrics from AWS documentation"""
        return [
            'MinMQCS',                      # Also uses OutputGroupName dimension
            'MqcsBlackFrameDetected',
            'MqcsFreezeFrameDetected',
            'MqcsContinuityCounterErrors',
            'FillMsec',
            'InputLossSeconds',
            'DroppedFrames',                # Uses Pipeline+Region dimensions, may return empty datapoints
        ]

    def get_metric_units(self) -> Dict[str, str]:
        """Content quality metric units"""
        return {
            'MinMQCS': 'Count',
            'MqcsBlackFrameDetected': 'Count',
            'MqcsFreezeFrameDetected': 'Count',
            'MqcsContinuityCounterErrors': 'Count',
            'FillMsec': 'Milliseconds',
            'InputLossSeconds': 'Seconds',
            'DroppedFrames': 'Count',
        }

    def _analyze_health(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze content quality health"""
        score = 100
        issues = []

        # MqcsBlackFrameDetected > 0 indicates black frames
        if metrics.get('MqcsBlackFrameDetected', {}).get('datapoints'):
            for dp in metrics['MqcsBlackFrameDetected']['datapoints']:
                if dp.get('Average', 0) > 0:
                    score -= 25
                    issues.append("MqcsBlackFrameDetected: black frames detected")
                    break

        # MqcsFreezeFrameDetected > 0 indicates frozen frames
        if metrics.get('MqcsFreezeFrameDetected', {}).get('datapoints'):
            for dp in metrics['MqcsFreezeFrameDetected']['datapoints']:
                if dp.get('Average', 0) > 0:
                    score -= 25
                    issues.append("MqcsFreezeFrameDetected: freeze frames detected")
                    break

        # MqcsContinuityCounterErrors > 0 indicates transport stream errors
        if metrics.get('MqcsContinuityCounterErrors', {}).get('datapoints'):
            total_errors = sum(dp.get('Average', 0) for dp in metrics['MqcsContinuityCounterErrors']['datapoints'])
            if total_errors > 0:
                score -= 15
                issues.append(f"MqcsContinuityCounterErrors: {total_errors}")

        # InputLossSeconds > 0 indicates input loss
        if metrics.get('InputLossSeconds', {}).get('datapoints'):
            total_loss = sum(dp.get('Average', 0) for dp in metrics['InputLossSeconds']['datapoints'])
            if total_loss > 0:
                score -= 20
                issues.append(f"InputLossSeconds: {total_loss}")

        return {
            'score': max(0, score),
            'status': 'EXCELLENT' if score >= 90 else 'GOOD' if score >= 70 else 'POOR',
            'issues': issues
        }
