"""MediaConnect thumbnail analysis tools"""
import boto3
import json
from typing import Dict, Any


class ThumbnailAnalyzer:
    def __init__(self):
        self.mediaconnect = boto3.client('mediaconnect')
        self.bedrock = boto3.client('bedrock-runtime')

    def describe_flow_thumbnail(self, flow_arn: str) -> Dict[str, Any]:
        """Get the current thumbnail from a MediaConnect flow and analyze it with Claude"""
        try:
            # Get thumbnail from MediaConnect
            thumbnail_response = self.mediaconnect.describe_flow_source_thumbnail(FlowArn=flow_arn)
            thumbnail_details = thumbnail_response.get('ThumbnailDetails', {})
            thumbnail_b64 = thumbnail_details.get('Thumbnail')

            if not thumbnail_b64:
                return {
                    'flow_arn': flow_arn,
                    'success': False,
                    'error': 'No thumbnail data available',
                    'note': 'Thumbnail may not be generated yet or flow may not be active'
                }

            # Analyze with Claude
            claude_description = self._analyze_with_claude(thumbnail_b64)

            return {
                'flow_arn': thumbnail_details.get('FlowArn', flow_arn),
                'success': True,
                'thumbnail_analysis': {
                    'description': claude_description,
                    'timecode': thumbnail_details.get('Timecode'),
                    'timestamp': thumbnail_details.get('Timestamp'),
                    'analyzed_by': 'Claude 4 Sonnet via Bedrock'
                },
                'thumbnail_metadata': {
                    'size_bytes': len(thumbnail_b64),
                    'format': 'JPEG (base64)',
                    'messages': thumbnail_details.get('ThumbnailMessages', [])
                }
            }

        except Exception as e:
            return {
                'flow_arn': flow_arn,
                'success': False,
                'error': str(e),
                'error_type': type(e).__name__,
                'note': 'Make sure the flow exists, has thumbnail generation enabled, and Bedrock access is configured'
            }

    def _analyze_with_claude(self, thumbnail_b64: str) -> str:
        """Analyze thumbnail with Claude via Bedrock"""
        message = {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Please analyze this MediaConnect flow thumbnail image and provide a detailed description. "
                        "Include information about: 1) What type of content appears to be streaming (video, graphics, text, etc.), "
                        "2) Visual quality and any technical issues you can observe, "
                        "3) Any visible artifacts, color bars, or technical patterns, "
                        "4) Overall assessment of the stream health based on the visual content."
                    )
                },
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": thumbnail_b64
                    }
                }
            ]
        }

        bedrock_request = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1000,
            "messages": [message]
        }

        bedrock_response = self.bedrock.invoke_model(
            modelId="global.anthropic.claude-sonnet-4-20250514-v1:0",
            body=json.dumps(bedrock_request)
        )

        response_body = json.loads(bedrock_response['body'].read())
        return response_body['content'][0]['text']
