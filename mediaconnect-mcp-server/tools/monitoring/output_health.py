"""Output health monitoring for MediaConnect"""
from typing import Dict, Any, List
from .base import BaseMonitor


class OutputHealthMonitor(BaseMonitor):
    """Monitor output health metrics"""

    def get_metrics_list(self) -> List[str]:
        """Output health metrics from AWS documentation"""
        return [
            'ConnectedOutputs',
            'OutputARQRequests',
            'OutputBitrate',
            'OutputConnected',
            'OutputConnectedReceivers',
            'OutputDisconnections',
            'OutputGeneratedAudioSamples',
            'OutputGeneratedVideoFrames',
            'OutputNotRecoveredPackets',
            'OutputResentPackets',
            'OutputRoundTripTime',
            'OutputTotalPackets',
            # CDI protocols
            'OutputDroppedPayloads',
            'OutputLatePayloads',
            'OutputTotalBytes',
            'OutputTotalPayloads',
        ]

    def get_metric_units(self) -> Dict[str, str]:
        """Output health metric units"""
        return {
            'ConnectedOutputs': 'Count',
            'OutputARQRequests': 'Count',
            'OutputBitrate': 'Bits/Second',
            'OutputConnected': 'None',
            'OutputConnectedReceivers': 'Count',
            'OutputDisconnections': 'Count',
            'OutputGeneratedAudioSamples': 'Count',
            'OutputGeneratedVideoFrames': 'Count',
            'OutputNotRecoveredPackets': 'Count',
            'OutputResentPackets': 'Count',
            'OutputRoundTripTime': 'Milliseconds',
            'OutputTotalPackets': 'Count',
            'OutputDroppedPayloads': 'Count',
            'OutputLatePayloads': 'Count',
            'OutputTotalBytes': 'Bytes',
            'OutputTotalPayloads': 'Count',
        }

    def _analyze_health(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze output health"""
        score = 100
        issues = []

        if metrics.get('OutputDisconnections', {}).get('datapoints'):
            total_disconnections = sum(dp.get('Sum', 0) for dp in metrics['OutputDisconnections']['datapoints'])
            if total_disconnections > 0:
                score -= 30
                issues.append(f"Output disconnections: {total_disconnections}")

        if metrics.get('OutputNotRecoveredPackets', {}).get('datapoints'):
            total_not_recovered = sum(dp.get('Sum', 0) for dp in metrics['OutputNotRecoveredPackets']['datapoints'])
            if total_not_recovered > 0:
                score -= 25
                issues.append(f"Output not recovered packets: {total_not_recovered}")

        if metrics.get('OutputDroppedPayloads', {}).get('datapoints'):
            total_dropped = sum(dp.get('Sum', 0) for dp in metrics['OutputDroppedPayloads']['datapoints'])
            if total_dropped > 0:
                score -= 20
                issues.append(f"Output dropped payloads: {total_dropped}")

        return {
            'score': max(0, score),
            'status': 'EXCELLENT' if score >= 90 else 'GOOD' if score >= 70 else 'POOR',
            'issues': issues
        }
