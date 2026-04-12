"""Comprehensive monitoring coordinator for MediaLive"""
from typing import Dict, Any
from .channel_health import ChannelHealthMonitor
from .input_health import InputHealthMonitor
from .output_health import OutputHealthMonitor
from .media_health import MediaHealthMonitor
from .content_quality import ContentQualityMonitor


class MonitoringCoordinator:
    """Coordinates all MediaLive monitoring categories"""

    def __init__(self):
        self.monitors = {
            'channel_health': ChannelHealthMonitor(),
            'input_health': InputHealthMonitor(),
            'output_health': OutputHealthMonitor(),
            'media_health': MediaHealthMonitor(),
            'content_quality': ContentQualityMonitor()
        }

    def get_all_metrics(self, channel_id: str, hours_back: int = 1) -> Dict[str, Any]:
        """Get all metrics across all categories"""
        try:
            results = {}
            for category, monitor in self.monitors.items():
                results[category] = monitor.get_metrics(channel_id, hours_back)

            return {
                'channel_id': channel_id,
                'time_range': f'{hours_back}h ago to now',
                'metrics_by_category': results,
                'comprehensive_health': self._analyze_comprehensive_health(results)
            }
        except Exception as e:
            return {'error': str(e), 'channel_id': channel_id}

    def get_category_metrics(self, category: str, channel_id: str, hours_back: int = 1) -> Dict[str, Any]:
        """Get metrics for a specific category"""
        if category not in self.monitors:
            return {'error': f'Unknown category: {category}', 'available_categories': list(self.monitors.keys())}
        return self.monitors[category].get_metrics(channel_id, hours_back)

    def check_channel_issues(self, channel_id: str, hours_back: int = 24) -> Dict[str, Any]:
        """Check for issues across all categories"""
        try:
            all_metrics = self.get_all_metrics(channel_id, hours_back)
            issues = []

            for category, category_data in all_metrics.get('metrics_by_category', {}).items():
                if 'category_health' in category_data:
                    health = category_data['category_health']
                    if health.get('issues'):
                        for issue in health['issues']:
                            issues.append({
                                'category': category,
                                'type': f'{category.title()} Issue',
                                'severity': 'HIGH' if health['score'] < 70 else 'MEDIUM',
                                'description': issue
                            })

            return {
                'channel_id': channel_id,
                'time_range': f'Past {hours_back} hours',
                'issues_found': len(issues),
                'issues': issues,
                'status': 'HEALTHY' if len(issues) == 0 else 'ISSUES_DETECTED',
                'overall_health': all_metrics.get('comprehensive_health', {})
            }
        except Exception as e:
            return {'error': str(e), 'channel_id': channel_id}

    def get_metrics_table(self, channel_id: str, hours_back: int = 6) -> Dict[str, Any]:
        """Get comprehensive metrics in tabular format for graphing"""
        try:
            key_metrics = {
                'channel_health': ['ActiveAlerts', 'FillMsec', 'DroppedFrames'],
                'input_health': ['NetworkIn', 'InputLossSeconds', 'RtpPacketsLost'],
                'output_health': ['NetworkOut', 'Output4xxErrors', 'Output5xxErrors'],
                'media_health': ['ChannelInputErrorSeconds', 'FillMsec'],
                'content_quality': ['MqcsBlackFrameDetected', 'MqcsFreezeFrameDetected', 'InputLossSeconds']
            }

            table_data = []

            for category, metrics in key_metrics.items():
                monitor = self.monitors[category]
                category_data = monitor.get_metrics(channel_id, hours_back)

                for metric_name in metrics:
                    if metric_name in category_data.get('metrics', {}):
                        metric_data = category_data['metrics'][metric_name]
                        if metric_data.get('datapoints'):
                            for dp in metric_data['datapoints']:
                                statistic = metric_data['statistic']
                                table_data.append({
                                    'timestamp': dp['Timestamp'].isoformat(),
                                    'category': category,
                                    'metric': metric_name,
                                    'value': dp[statistic],
                                    'unit': monitor.get_metric_units().get(metric_name, 'Count'),
                                    'statistic': statistic
                                })

            table_data.sort(key=lambda x: x['timestamp'])

            return {
                'channel_id': channel_id,
                'time_range': f'{hours_back}h ago to now',
                'data_points': len(table_data),
                'table_data': table_data,
                'chart_ready': True,
                'categories_included': list(key_metrics.keys())
            }
        except Exception as e:
            return {'error': str(e), 'channel_id': channel_id}

    def _analyze_comprehensive_health(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze overall health across all categories"""
        total_score = 0
        total_issues = 0
        category_scores = {}

        for category, category_data in results.items():
            if 'category_health' in category_data:
                health = category_data['category_health']
                category_scores[category] = health
                total_score += health.get('score', 0)
                total_issues += len(health.get('issues', []))

        avg_score = total_score / len(results) if results else 0

        return {
            'overall_health_score': max(0, int(avg_score)),
            'status': 'EXCELLENT' if avg_score >= 90 else 'GOOD' if avg_score >= 70 else 'POOR',
            'category_scores': category_scores,
            'total_issues': total_issues
        }
