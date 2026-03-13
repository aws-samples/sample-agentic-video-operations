"""Media health monitoring for MediaConnect"""
from typing import Dict, Any, List
from .base import BaseMonitor


class MediaHealthMonitor(BaseMonitor):
    """Monitor media health metrics"""

    def get_metrics_list(self) -> List[str]:
        """Media health metrics from AWS documentation"""
        return [
            'ConnectionAttempts',
            'ConsecutiveDrops',
            'ConsecutiveNotRecovered',
            'SourceJitter',
            'SourceLatency',
            'SourceUptime',
        ]

    def get_metric_units(self) -> Dict[str, str]:
        """Media health metric units"""
        return {
            'ConnectionAttempts': 'Count',
            'ConsecutiveDrops': 'Count',
            'ConsecutiveNotRecovered': 'Count',
            'SourceJitter': 'Milliseconds',
            'SourceLatency': 'Milliseconds',
            'SourceUptime': 'Count',
        }

    def _analyze_health(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze media health"""
        score = 100
        issues = []

        if metrics.get('ConnectionAttempts', {}).get('datapoints'):
            total_attempts = sum(dp.get('Sum', 0) for dp in metrics['ConnectionAttempts']['datapoints'])
            if total_attempts > 0:
                score -= 20
                issues.append(f"Connection attempts: {total_attempts}")

        if metrics.get('ConsecutiveDrops', {}).get('datapoints'):
            max_drops = max((dp.get('Maximum', 0) for dp in metrics['ConsecutiveDrops']['datapoints']), default=0)
            if max_drops > 0:
                score -= 30
                issues.append(f"Max consecutive drops: {max_drops}")

        if metrics.get('SourceJitter', {}).get('datapoints'):
            jitter_dps = metrics['SourceJitter']['datapoints']
            avg_jitter = sum(dp.get('Average', 0) for dp in jitter_dps) / len(jitter_dps)
            if avg_jitter > 100:
                score -= 15
                issues.append(f"High jitter: {avg_jitter:.1f}ms")

        if metrics.get('SourceLatency', {}).get('datapoints'):
            latency_dps = metrics['SourceLatency']['datapoints']
            avg_latency = sum(dp.get('Average', 0) for dp in latency_dps) / len(latency_dps)
            if avg_latency > 1000:
                score -= 10
                issues.append(f"High latency: {avg_latency:.1f}ms")

        return {
            'score': max(0, score),
            'status': 'EXCELLENT' if score >= 90 else 'GOOD' if score >= 70 else 'POOR',
            'issues': issues
        }
