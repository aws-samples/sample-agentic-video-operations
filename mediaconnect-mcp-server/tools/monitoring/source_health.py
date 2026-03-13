"""Source health monitoring for MediaConnect"""
from typing import Dict, Any, List
from .base import BaseMonitor


class SourceHealthMonitor(BaseMonitor):
    """Monitor source health metrics"""

    def get_metrics_list(self) -> List[str]:
        """Source health metrics from AWS documentation"""
        return [
            'SourceARQRecovered',
            'SourceARQRequests',
            'SourceBitRate',
            'SourceConnected',
            'SourceDisconnections',
            'SourceDroppedPackets',
            'SourceFECPackets',
            'SourceFECRecovered',
            'SourceMergeActive',
            'SourceSelected',
            'SourceMergeLatency',
            'SourceMergeStatusWarnMismatch',
            'SourceMergeStatusWarnSolo',
            'SourceNotRecoveredPackets',
            'SourceMissingPackets',
            'SourceOverflowPackets',
            'SourcePacketLossPercent',
            'SourceRecoveredPackets',
            'SourceRoundTripTime',
            'SourceTotalPackets',
            'SourceTotalBytes',
            'SourceDroppedPayloads',
            'SourceLatePayloads',
            'SourceTotalPayloads',
            # TR 101 290 Priority 1
            'SourceContinuityCounter',
            'SourcePATError',
            'SourcePIDError',
            'SourcePMTError',
            'SourceTSByteError',
            'SourceTSSyncLoss',
            # TR 101 290 Priority 2
            'SourceCATError',
            'SourceCRCError',
            'SourcePCRAccuracyError',
            'SourcePCRError',
            'SourcePTSError',
            'SourceTransportError',
        ]

    def get_metric_units(self) -> Dict[str, str]:
        """Source health metric units"""
        return {
            'SourceARQRecovered': 'Count',
            'SourceARQRequests': 'Count',
            'SourceBitRate': 'Bits/Second',
            'SourceConnected': 'None',
            'SourceDisconnections': 'Count',
            'SourceDroppedPackets': 'Count',
            'SourceFECPackets': 'Count',
            'SourceFECRecovered': 'Count',
            'SourceMergeActive': 'None',
            'SourceSelected': 'None',
            'SourceMergeLatency': 'Milliseconds',
            'SourceMergeStatusWarnMismatch': 'Count',
            'SourceMergeStatusWarnSolo': 'Count',
            'SourceNotRecoveredPackets': 'Count',
            'SourceMissingPackets': 'Count',
            'SourceOverflowPackets': 'Count',
            'SourcePacketLossPercent': 'Percent',
            'SourceRecoveredPackets': 'Count',
            'SourceRoundTripTime': 'Milliseconds',
            'SourceTotalPackets': 'Count',
            'SourceTotalBytes': 'Bytes',
            'SourceDroppedPayloads': 'Count',
            'SourceLatePayloads': 'Count',
            'SourceTotalPayloads': 'Count',
            'SourceContinuityCounter': 'Count',
            'SourcePATError': 'Count',
            'SourcePIDError': 'Count',
            'SourcePMTError': 'Count',
            'SourceTSByteError': 'Count',
            'SourceTSSyncLoss': 'Count',
            'SourceCATError': 'Count',
            'SourceCRCError': 'Count',
            'SourcePCRAccuracyError': 'Count',
            'SourcePCRError': 'Count',
            'SourcePTSError': 'Count',
            'SourceTransportError': 'Count',
        }

    def _analyze_health(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze source health"""
        score = 100
        issues = []

        if metrics.get('SourceDisconnections', {}).get('datapoints'):
            total_disconnections = sum(dp.get('Sum', 0) for dp in metrics['SourceDisconnections']['datapoints'])
            if total_disconnections > 0:
                score -= 30
                issues.append(f"Source disconnections: {total_disconnections}")

        if metrics.get('SourceDroppedPackets', {}).get('datapoints'):
            total_drops = sum(dp.get('Sum', 0) for dp in metrics['SourceDroppedPackets']['datapoints'])
            if total_drops > 0:
                score -= 25
                issues.append(f"Source dropped packets: {total_drops}")

        merge_warnings = ['SourceMergeStatusWarnMismatch', 'SourceMergeStatusWarnSolo']
        for warning_metric in merge_warnings:
            if metrics.get(warning_metric, {}).get('datapoints'):
                total_warnings = sum(dp.get('Sum', 0) for dp in metrics[warning_metric]['datapoints'])
                if total_warnings > 0:
                    score -= 15
                    issues.append(f"{warning_metric}: {total_warnings}")

        return {
            'score': max(0, score),
            'status': 'EXCELLENT' if score >= 90 else 'GOOD' if score >= 70 else 'POOR',
            'issues': issues
        }
