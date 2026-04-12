"""MediaLive thumbnail analysis tools"""
import json
import os
from typing import Dict, Any, Optional
from ..utils.aws_clients import aws_clients

THUMBNAIL_MODEL_ID = os.getenv(
    "THUMBNAIL_MODEL_ID",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
)

_REGION = os.getenv("AWS_REGION", "us-west-2")


class ThumbnailAnalyzer:
    def __init__(self, model_id: str | None = None):
        self.medialive = aws_clients.get_client('medialive', region_name=_REGION)
        self.bedrock = aws_clients.get_client('bedrock-runtime', region_name=_REGION)
        self.model_id = model_id or THUMBNAIL_MODEL_ID
    
    def describe_channel_thumbnail(self, channel_id: str, pipeline_id: str = "0") -> Dict[str, Any]:
        """Get the current thumbnail from a MediaLive channel and analyze it with Claude"""
        try:
            # Get thumbnail from MediaLive
            thumbnail_response = self.medialive.describe_thumbnails(
                ChannelId=channel_id,
                PipelineId=pipeline_id,
                ThumbnailType='CURRENT_ACTIVE'
            )
            
            thumbnail_details = thumbnail_response.get('ThumbnailDetails', [])
            
            if not thumbnail_details or not thumbnail_details[0].get('Thumbnails'):
                return {
                    'channel_id': channel_id,
                    'pipeline_id': pipeline_id,
                    'success': False,
                    'error': 'No thumbnail data available',
                    'note': 'Thumbnail may not be generated yet, channel may not be running, or thumbnails may be disabled'
                }
            
            # Extract thumbnail data
            pipeline_detail = thumbnail_details[0]
            thumbnail = pipeline_detail['Thumbnails'][0]
            thumbnail_b64 = thumbnail.get('Body')
            
            if not thumbnail_b64:
                return {
                    'channel_id': channel_id,
                    'pipeline_id': pipeline_id,
                    'success': False,
                    'error': 'Thumbnail body is empty',
                    'note': 'Channel may be in transition or thumbnail generation failed'
                }
            
            # Analyze with Claude
            claude_description = self._analyze_with_claude(thumbnail_b64)
            
            return {
                'channel_id': channel_id,
                'pipeline_id': pipeline_detail.get('PipelineId', pipeline_id),
                'success': True,
                'thumbnail_analysis': {
                    'description': claude_description,
                    'timestamp': thumbnail.get('TimeStamp'),
                    'content_type': thumbnail.get('ContentType', 'image/jpeg'),
                    'thumbnail_type': thumbnail.get('ThumbnailType', 'CURRENT_ACTIVE'),
                    'analyzed_by': f'{self.model_id} via Bedrock'
                },
                'thumbnail_metadata': {
                    'size_bytes': len(thumbnail_b64),
                    'format': 'JPEG (base64)',
                    'pipeline_id': pipeline_detail.get('PipelineId')
                }
            }
            
        except Exception as e:
            return {
                'channel_id': channel_id,
                'pipeline_id': pipeline_id,
                'success': False,
                'error': str(e),
                'error_type': type(e).__name__,
                'note': 'Make sure the channel exists, is running, has thumbnails enabled, and Bedrock access is configured'
            }
    
    def _analyze_with_claude(self, thumbnail_b64: str) -> str:
        """Analyze thumbnail with Claude via Bedrock"""
        message = {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "Please analyze this MediaLive channel thumbnail image and provide a detailed description. Include information about: 1) What type of content appears to be streaming (video, graphics, text, etc.), 2) Visual quality and any technical issues you can observe, 3) Any visible artifacts, color bars, or technical patterns, 4) Overall assessment of the stream health based on the visual content."
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
            modelId=self.model_id,
            body=json.dumps(bedrock_request)
        )
        
        response_body = json.loads(bedrock_response['body'].read())
        return response_body['content'][0]['text']
