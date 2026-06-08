from datetime import datetime, timedelta, timezone
from typing import Optional
import os
from ..utils.aws_clients import aws_clients
from .thumbnails import ThumbnailAnalyzer
from .constants import DEFAULT_CHANNEL_ID, get_channel_id
from .truncation import truncate_metrics_response, truncate_logs_response

# AWS clients using singletons — region from env
_REGION = os.getenv("AWS_REGION", "us-west-2")
medialive = aws_clients.get_client('medialive', region_name=_REGION)
cloudwatch = aws_clients.get_client('cloudwatch', region_name=_REGION)
logs = aws_clients.get_client('logs', region_name=_REGION)

# Initialize thumbnail analyzer
thumbnail_analyzer = ThumbnailAnalyzer()


def current_time():
    """Get the current time"""
    return datetime.now().isoformat()


def list_channels():
    """List all MediaLive channels"""
    try:
        paginator = medialive.get_paginator('list_channels')
        channels = []
        for page in paginator.paginate():
            channels.extend(page.get('Channels', []))

        result = f"Found {len(channels)} MediaLive channels:\n\n"
        for channel in channels:
            default_marker = " (DEFAULT)" if DEFAULT_CHANNEL_ID and channel['Id'] == DEFAULT_CHANNEL_ID else ""
            result += f"• {channel['Name']} (ID: {channel['Id']}, ARN: {channel['Arn']}) - State: {channel['State']}{default_marker}\n"

        return result
    except Exception as e:
        return f"Error listing channels: {str(e)}"


def describe_channel(channel_id: Optional[str] = None):
    """Get detailed channel information and health status"""
    channel_id = get_channel_id(channel_id)
    try:
        response = medialive.describe_channel(ChannelId=channel_id)
        channel = response

        # Basic channel info
        result = f"Channel: {channel['Name']} (ID: {channel_id}, ARN: {channel['Arn']})\n"
        result += f"State: {channel['State']}\n"
        result += f"Channel Class: {channel.get('ChannelClass', 'N/A')}\n"

        # Input attachments with artifact descriptions
        input_attachments = channel.get('InputAttachments', [])
        result += f"\nAvailable Input Sources ({len(input_attachments)}):\n"

        for attachment in input_attachments:
            name = attachment['InputAttachmentName']
            result += f"  • {name}\n"

        # Pipeline info
        pipeline_details = channel.get('PipelineDetails', [])
        if pipeline_details:
            result += f"\nPipeline Status:\n"
            for i, pipeline in enumerate(pipeline_details):
                active_input = pipeline.get('ActiveInputAttachmentName', 'N/A')
                result += f"  Pipeline {i}: Active Input = {active_input}\n"

        return result
    except Exception as e:
        return f"Error describing channel {channel_id}: {str(e)}"


def start_channel(channel_id: Optional[str] = None):
    """Start a MediaLive channel"""
    channel_id = get_channel_id(channel_id)
    try:
        medialive.start_channel(ChannelId=channel_id)
        return f"Started channel {channel_id}"
    except Exception as e:
        return f"Error starting channel {channel_id}: {str(e)}"


def stop_channel(channel_id: Optional[str] = None):
    """Stop a MediaLive channel"""
    channel_id = get_channel_id(channel_id)
    try:
        medialive.stop_channel(ChannelId=channel_id)
        return f"Stopped channel {channel_id}"
    except Exception as e:
        return f"Error stopping channel {channel_id}: {str(e)}"


def get_channel_metrics(channel_id: Optional[str] = None, hours_back: int = 1):
    """Get CloudWatch metrics for a MediaLive channel"""
    channel_id = get_channel_id(channel_id)
    try:
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=hours_back)

        # Key MediaLive metrics to monitor
        metrics = [
            'ActiveInputFailoverCount',
            'InputVideoFrameRate',
            'OutputVideoFrameRate',
            'NetworkIn',
            'NetworkOut',
            'FillMsec',
            'AudioSilenceDetected',
            'VideoBlackFrameDetected'
        ]

        result = f"MediaLive Metrics for Channel {channel_id} (Last {hours_back}h):\n\n"

        for metric_name in metrics:
            try:
                response = cloudwatch.get_metric_statistics(
                    Namespace='AWS/MediaLive',
                    MetricName=metric_name,
                    Dimensions=[
                        {'Name': 'ChannelId', 'Value': channel_id},
                        {'Name': 'Pipeline', 'Value': '0'},
                    ],
                    StartTime=start_time,
                    EndTime=end_time,
                    Period=300,  # 5 minutes
                    Statistics=['Average', 'Maximum']
                )

                datapoints = response.get('Datapoints', [])
                truncated = truncate_metrics_response(datapoints)
                datapoints = truncated["datapoints"]
                if datapoints:
                    latest = max(datapoints, key=lambda x: x['Timestamp'])
                    trunc_marker = " [truncated]" if truncated["_truncated"] else ""
                    result += f"• {metric_name}: Avg={latest.get('Average', 0):.2f}, Max={latest.get('Maximum', 0):.2f}{trunc_marker}\n"
                else:
                    result += f"• {metric_name}: No data\n"

            except Exception as metric_error:
                result += f"• {metric_name}: Error - {str(metric_error)}\n"

        return result
    except Exception as e:
        return f"Error getting metrics for channel {channel_id}: {str(e)}"


def get_channel_logs(channel_id: Optional[str] = None, hours_back: int = 1):
    """Get CloudWatch logs for a MediaLive channel"""
    channel_id = get_channel_id(channel_id)
    try:
        log_group_name = f"/aws/medialive/{channel_id}"
        end_time = int(datetime.now(timezone.utc).timestamp() * 1000)
        start_time = int((datetime.now(timezone.utc) - timedelta(hours=hours_back)).timestamp() * 1000)

        response = logs.filter_log_events(
            logGroupName=log_group_name,
            startTime=start_time,
            endTime=end_time,
            limit=50
        )

        events = response.get('events', [])
        truncated = truncate_logs_response(events)
        events = truncated["events"]
        result = f"Recent logs for Channel {channel_id} (Last {hours_back}h):\n\n"

        if not events:
            result += "No log events found in the specified time range.\n"
        else:
            if truncated["_truncated"]:
                result += f"[Showing {len(events)} of {truncated['_original_count']} events]\n\n"
            for event in events:
                timestamp = datetime.fromtimestamp(event['timestamp'] / 1000)
                result += f"[{timestamp}] {event['message']}\n"

        return result
    except Exception as e:
        return f"Error getting logs for channel {channel_id}: {str(e)}"



# Quick artifact switching tools
def _immediate_switch(channel_id: str, input_name: str, artifact_type: str):
    """Helper function for immediate input switching"""
    try:
        action_name = f"Switch_to_{input_name}_{datetime.now().strftime('%H%M%S')}"

        action = {
            'ActionName': action_name,
            'ScheduleActionStartSettings': {
                'ImmediateModeScheduleActionStartSettings': {}
            },
            'ScheduleActionSettings': {
                'InputSwitchSettings': {
                    'InputAttachmentNameReference': input_name
                }
            }
        }

        medialive.batch_update_schedule(
            ChannelId=channel_id,
            Creates={'ScheduleActions': [action]}
        )

        return f"✅ Switched to {input_name}"
    except Exception as e:
        return f"❌ Error switching to {input_name}: {str(e)}"


def describe_channel_thumbnail(channel_id: Optional[str] = None, pipeline_id: str = "0"):
    """Get the current thumbnail from a MediaLive channel and analyze it with Claude to provide a description"""
    channel_id = get_channel_id(channel_id)
    return thumbnail_analyzer.describe_channel_thumbnail(channel_id, pipeline_id)
