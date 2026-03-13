"""Flow health monitoring for MediaConnect"""
from typing import Dict, Any, List
from .base import BaseMonitor


class FlowHealthMonitor(BaseMonitor):
    """Monitor flow health metrics"""

    def get_metrics_list(self) -> List[str]:
        """Flow health metrics from AWS documentation"""
        return [
            'ARQRecovered',
            'ARQRequests',
            'BitRate',
            'Connected',
            'Disconnections',
            'DroppedPackets',
            'FECPackets',
            'FECRecovered',
            'MergeActive',
            'MergeLatency',
            'NotRecoveredPackets',
            'OverflowPackets',
            'PacketLossPercent',
            'RecoveredPackets',
            'RoundTripTime',
            'TotalPackets',
            'FailoverSwitches',
            # TR 101 290 Priority 1
            'ContinuityCounter',
            'PATError',
            'PIDError',
            'PMTError',
            'TSByteError',
            'TSSyncLoss',
            # TR 101 290 Priority 2
            'CATError',
            'CRCError',
            'PCRAccuracyError',
            'PCRError',
            'PTSError',
        ]

    def get_metric_units(self) -> Dict[str, str]:
        """Flow health metric units"""
        return {
            'ARQRecovered': 'Count',
            'ARQRequests': 'Count',
            'BitRate': 'Bits/Second',
            'Connected': 'None',
            'Disconnections': 'Count',
            'DroppedPackets': 'Count',
            'FECPackets': 'Count',
            'FECRecovered': 'Count',
            'MergeActive': 'None',
            'MergeLatency': 'Milliseconds',
            'NotRecoveredPackets': 'Count',
            'OverflowPackets': 'Count',
            'PacketLossPercent': 'Percent',
            'RecoveredPackets': 'Count',
            'RoundTripTime': 'Milliseconds',
            'TotalPackets': 'Count',
            'FailoverSwitches': 'Count',
            'ContinuityCounter': 'Count',
            'PATError': 'Count',
            'PIDError': 'Count',
            'PMTError': 'Count',
            'TSByteError': 'Count',
            'TSSyncLoss': 'Count',
            'CATError': 'Count',
            'CRCError': 'Count',
            'PCRAccuracyError': 'Count',
            'PCRError': 'Count',
            'PTSError': 'Count',
        }

    def _analyze_health(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze flow health"""
        score = 100
        issues = []

        # Check for packet loss
        if metrics.get('DroppedPackets', {}).get('datapoints'):
            total_drops = sum(dp.get('Sum', 0) for dp in metrics['DroppedPackets']['datapoints'])
            if total_drops > 0:
                score -= 30
                issues.append(f"Dropped packets: {total_drops}")

        # Check for disconnections
        if metrics.get('Disconnections', {}).get('datapoints'):
            total_disconnections = sum(dp.get('Sum', 0) for dp in metrics['Disconnections']['datapoints'])
            if total_disconnections > 0:
                score -= 25
                issues.append(f"Disconnections: {total_disconnections}")

        # Check TR 101 290 errors
        tr_errors = ['PATError', 'PIDError', 'PMTError', 'TSByteError', 'TSSyncLoss']
        for error_metric in tr_errors:
            if metrics.get(error_metric, {}).get('datapoints'):
                total_errors = sum(dp.get('Sum', 0) for dp in metrics[error_metric]['datapoints'])
                if total_errors > 0:
                    score -= 10
                    issues.append(f"{error_metric}: {total_errors}")

        return {
            'score': max(0, score),
            'status': 'EXCELLENT' if score >= 90 else 'GOOD' if score >= 70 else 'POOR',
            'issues': issues
        }
