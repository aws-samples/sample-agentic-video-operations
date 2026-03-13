"""MediaConnect flow management tools"""
import boto3
from typing import Dict, Any


class FlowManager:
    def __init__(self):
        self.client = boto3.client('mediaconnect')

    def list_flows(self) -> Dict[str, Any]:
        """List all MediaConnect flows"""
        try:
            return self.client.list_flows()
        except Exception as e:
            return {"error": str(e)}

    def describe_flow(self, flow_arn: str) -> Dict[str, Any]:
        """Describe a specific MediaConnect flow by ARN with EventBridge-style health monitoring"""
        try:
            response = self.client.describe_flow(FlowArn=flow_arn)
            return self._add_health_monitoring(response)
        except Exception as e:
            return {"error": str(e)}

    def start_flow(self, flow_arn: str) -> Dict[str, Any]:
        """Start a MediaConnect flow"""
        try:
            response = self.client.start_flow(FlowArn=flow_arn)
            return {
                'success': True,
                'flow_arn': response.get('flowArn'),
                'status': response.get('status'),
                'action': 'STARTED',
                'note': 'Flow start initiated. Status will transition from STANDBY to STARTING to ACTIVE.'
            }
        except Exception as e:
            return {
                'success': False,
                'flow_arn': flow_arn,
                'error': str(e),
                'action': 'START_FAILED'
            }

    def stop_flow(self, flow_arn: str) -> Dict[str, Any]:
        """Stop a MediaConnect flow"""
        try:
            response = self.client.stop_flow(FlowArn=flow_arn)
            return {
                'success': True,
                'flow_arn': response.get('flowArn'),
                'status': response.get('status'),
                'action': 'STOPPED',
                'note': 'Flow stop initiated. Status will transition from ACTIVE to STOPPING to STANDBY.'
            }
        except Exception as e:
            return {
                'success': False,
                'flow_arn': flow_arn,
                'error': str(e),
                'action': 'STOP_FAILED'
            }

    def describe_flow_source_metadata(self, flow_arn: str) -> Dict[str, Any]:
        """Get detailed source metadata for a MediaConnect flow"""
        try:
            response = self.client.describe_flow_source_metadata(FlowArn=flow_arn)
            return {
                'success': True,
                'flow_arn': flow_arn,
                'metadata': response
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'flow_arn': flow_arn
            }

    def _add_health_monitoring(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Add health monitoring section following EventBridge event structure"""
        health_status = {
            'flow_health': 'HEALTHY',
            'alerts': [],
            'source_health': {},
            'output_health': {},
            'tr101_indicators': {}
        }

        # Check for critical errors (Alert events)
        if 'messages' in response and 'errors' in response['messages']:
            errors = response['messages']['errors']
            if errors:
                health_status['flow_health'] = 'CRITICAL'
                health_status['alerts'] = [
                    {
                        'type': 'MediaConnect Alert',
                        'severity': 'CRITICAL',
                        'error_count': len(errors),
                        'errors': errors,
                        'action_required': 'IMMEDIATE ATTENTION - Flow has active errors'
                    }
                ]

        # Analyze flow status for health indicators
        flow = response.get('flow', {})
        flow_status = flow.get('status', 'UNKNOWN')

        # Source health analysis
        source = flow.get('source', {})
        if source:
            health_status['source_health'] = {
                'state': 'CONNECTED' if flow_status == 'ACTIVE' else 'DISCONNECTED',
                'ingest_ip': source.get('ingestIp', 'N/A'),
                'protocol': source.get('transport', {}).get('protocol', 'N/A')
            }

        # Output health analysis
        outputs = flow.get('outputs', [])
        if outputs:
            health_status['output_health'] = {
                'total_outputs': len(outputs),
                'outputs': [
                    {
                        'name': output.get('name', 'Unknown'),
                        'status': output.get('outputStatus', 'UNKNOWN'),
                        'protocol': output.get('transport', {}).get('protocol', 'N/A')
                    }
                    for output in outputs
                ]
            }

        # Add RED ALERT section if unhealthy
        if health_status['flow_health'] == 'CRITICAL':
            response['🚨_RED_ALERT'] = {
                'status': '🔴 CRITICAL HEALTH ISSUES DETECTED',
                'flow_health': health_status['flow_health'],
                'alerts': health_status['alerts'],
                'monitoring_note': 'This flow has active errors. Check EventBridge for real-time alerts.'
            }

        # Add health monitoring section
        response['health_monitoring'] = health_status

        return response
