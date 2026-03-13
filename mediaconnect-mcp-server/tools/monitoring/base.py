"""Base monitoring class for MediaConnect CloudWatch metrics"""
import boto3
from datetime import datetime, timedelta
from typing import Dict, Any, List
from abc import ABC, abstractmethod


class BaseMonitor(ABC):
    """Base class for MediaConnect CloudWatch monitoring"""

    def __init__(self):
        self.cloudwatch = boto3.client('cloudwatch')

    @abstractmethod
    def get_metrics_list(self) -> List[str]:
        """Return list of metrics for this monitor"""
        pass

    @abstractmethod
    def get_metric_units(self) -> Dict[str, str]:
        """Return metric name to unit mapping"""
        pass

    def get_metrics(self, flow_arn: str, hours_back: int = 1) -> Dict[str, Any]:
        """Get metrics for this category"""
        try:
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(hours=hours_back)

            metrics = self.get_metrics_list()
            results = {}

            for metric_name in metrics:
                metric_data = self._get_metric_statistics(
                    metric_name=metric_name,
                    flow_arn=flow_arn,
                    start_time=start_time,
                    end_time=end_time
                )
                results[metric_name] = metric_data

            return {
                'flow_arn': flow_arn,
                'category': self.__class__.__name__.replace('Monitor', '').lower(),
                'time_range': f'{hours_back}h ago to now',
                'metrics': results,
                'category_health': self._analyze_health(results)
            }

        except Exception as e:
            return {'error': str(e), 'flow_arn': flow_arn}

    def _get_metric_statistics(self, metric_name: str, flow_arn: str,
                               start_time: datetime, end_time: datetime,
                               statistic: str = 'Average', period: int = 300) -> Dict[str, Any]:
        """Get CloudWatch metric statistics"""
        try:
            response = self.cloudwatch.get_metric_statistics(
                Namespace='AWS/MediaConnect',
                MetricName=metric_name,
                Dimensions=[
                    {
                        'Name': 'FlowARN',
                        'Value': flow_arn
                    }
                ],
                StartTime=start_time,
                EndTime=end_time,
                Period=period,
                Statistics=[statistic]
            )

            datapoints = sorted(response['Datapoints'], key=lambda x: x['Timestamp'])
            unit = self.get_metric_units().get(metric_name, 'Count')
            if response.get('Datapoints'):
                unit = response['Datapoints'][0].get('Unit', unit)

            return {
                'metric_name': metric_name,
                'statistic': statistic,
                'datapoints': datapoints,
                'unit': unit
            }

        except Exception as e:
            return {'error': str(e), 'metric_name': metric_name}

    def _analyze_health(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze health for this category - override in subclasses"""
        return {
            'score': 100,
            'status': 'EXCELLENT',
            'issues': []
        }
