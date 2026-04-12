"""Input health monitoring for MediaLive"""
from typing import Dict, Any, List
from .base import BaseMonitor


class InputHealthMonitor(BaseMonitor):
    """Monitor input-level health metrics"""

    def get_metrics_list(self) -> List[str]:
        """Input health metrics from AWS documentation"""
        return [
            'NetworkIn',
            'InputLossSeconds',
            'InputVideoFrameRate',
            'RtpPacketsReceived',
            'RtpPacketsLost',
            'RtpPacketsRecoveredViaFec',
            'FecRowPacketsReceived',
            'FecColumnPacketsReceived',
            'ChannelInputErrorSeconds',
            'PrimaryInputActive',
        ]

    def get_metric_units(self) -> Dict[str, str]:
        """Input health metric units"""
        return {
            'NetworkIn': 'Megabits/Second',
            'InputLossSeconds': 'Seconds',
            'InputVideoFrameRate': 'Count',
            'RtpPacketsReceived': 'Count',
            'RtpPacketsLost': 'Count',
            'RtpPacketsRecoveredViaFec': 'Count',
            'FecRowPacketsReceived': 'Count',
            'FecColumnPacketsReceived': 'Count',
            'ChannelInputErrorSeconds': 'Seconds',
            'PrimaryInputActive': 'Count',
        }

    def _analyze_health(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze input health"""
        score = 100
        issues = []

        # InputLossSeconds > 0 is a significant concern
        if metrics.get('InputLossSeconds', {}).get('datapoints'):
            total_loss = sum(dp.get('Average', 0) for dp in metrics['InputLossSeconds']['datapoints'])
            if total_loss > 0:
                score -= 30
                issues.append(f"InputLossSeconds: {total_loss}")

        # RtpPacketsLost > 0 indicates packet loss
        if metrics.get('RtpPacketsLost', {}).get('datapoints'):
            total_lost = sum(dp.get('Average', 0) for dp in metrics['RtpPacketsLost']['datapoints'])
            if total_lost > 0:
                score -= 25
                issues.append(f"RtpPacketsLost: {total_lost}")

        # ChannelInputErrorSeconds > 0 indicates input errors
        if metrics.get('ChannelInputErrorSeconds', {}).get('datapoints'):
            total_errors = sum(dp.get('Average', 0) for dp in metrics['ChannelInputErrorSeconds']['datapoints'])
            if total_errors > 0:
                score -= 20
                issues.append(f"ChannelInputErrorSeconds: {total_errors}")

        return {
            'score': max(0, score),
            'status': 'EXCELLENT' if score >= 90 else 'GOOD' if score >= 70 else 'POOR',
            'issues': issues
        }
