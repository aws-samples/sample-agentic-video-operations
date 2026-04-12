from datetime import datetime, timedelta
import os
from typing import Dict, Any, Optional
from ..utils.aws_clients import aws_clients
from .constants import DEFAULT_CHANNEL_ID, get_channel_id

# AWS client using singleton — region from env
_REGION = os.getenv("AWS_REGION", "us-west-2")
medialive = aws_clients.get_client('medialive', region_name=_REGION)

def describe_schedule(channel_id: Optional[str] = None):
    """Get the current schedule for a MediaLive channel"""
    channel_id = get_channel_id(channel_id)
    try:
        response = medialive.describe_schedule(ChannelId=channel_id)
        schedule_actions = response.get('ScheduleActions', [])
        
        if not schedule_actions:
            return f"No schedule actions found for channel {channel_id}"
        
        result = f"Schedule for Channel {channel_id} ({len(schedule_actions)} actions):\n\n"
        
        for action in schedule_actions:
            action_name = action.get('ActionName', 'N/A')
            start_time = action.get('ScheduleActionStartSettings', {})
            action_settings = action.get('ScheduleActionSettings', {})
            action_type = list(action_settings.keys())[0] if action_settings else 'Unknown'
            
            result += f"• {action_name} ({action_type})\n"
            
            # Show input switch details
            if 'InputSwitchSettings' in action_settings:
                input_ref = action_settings['InputSwitchSettings'].get('InputAttachmentNameReference', 'N/A')
                result += f"  → Switch to: {input_ref}\n"
            
            if 'FixedModeScheduleActionStartSettings' in start_time:
                time_str = start_time['FixedModeScheduleActionStartSettings'].get('Time', 'N/A')
                result += f"  Start: {time_str}\n"
            elif 'FollowModeScheduleActionStartSettings' in start_time:
                follow_point = start_time['FollowModeScheduleActionStartSettings'].get('FollowPoint', 'N/A')
                result += f"  Follow: {follow_point}\n"
            elif 'ImmediateModeScheduleActionStartSettings' in start_time:
                result += f"  Start: Immediate\n"
            result += "\n"
        
        return result
    except Exception as e:
        return f"Error describing schedule for channel {channel_id}: {str(e)}"

def create_input_switch_action(channel_id: Optional[str] = None, action_name: str = "", input_attachment_name: str = "", start_time: str = ""):
    """Create an input switch schedule action"""
    channel_id = get_channel_id(channel_id)
    try:
        action = {
            'ActionName': action_name,
            'ScheduleActionStartSettings': {
                'FixedModeScheduleActionStartSettings': {
                    'Time': start_time
                }
            },
            'ScheduleActionSettings': {
                'InputSwitchSettings': {
                    'InputAttachmentNameReference': input_attachment_name
                }
            }
        }
        
        response = medialive.batch_update_schedule(
            ChannelId=channel_id,
            Creates={'ScheduleActions': [action]}
        )
        
        return f"Created input switch action '{action_name}' for channel {channel_id} at {start_time}"
    except Exception as e:
        return f"Error creating input switch action: {str(e)}"

def create_scte35_action(channel_id: Optional[str] = None, action_name: str = "", start_time: str = "", splice_event_id: int = 0, duration: Optional[int] = None):
    """Create a SCTE-35 splice insert schedule action"""
    channel_id = get_channel_id(channel_id)
    try:
        scte35_settings = {
            'Scte35SpliceInsertSettings': {
                'SpliceEventId': splice_event_id
            }
        }
        
        if duration:
            scte35_settings['Scte35SpliceInsertSettings']['Duration'] = duration
        
        action = {
            'ActionName': action_name,
            'ScheduleActionStartSettings': {
                'FixedModeScheduleActionStartSettings': {
                    'Time': start_time
                }
            },
            'ScheduleActionSettings': scte35_settings
        }
        
        response = medialive.batch_update_schedule(
            ChannelId=channel_id,
            Creates={'ScheduleActions': [action]}
        )
        
        return f"Created SCTE-35 action '{action_name}' for channel {channel_id} at {start_time}"
    except Exception as e:
        return f"Error creating SCTE-35 action: {str(e)}"

def create_pause_action(channel_id: Optional[str] = None, action_name: str = "", start_time: str = "", pipeline_id: str = "PIPELINE_0"):
    """Create a pipeline pause schedule action"""
    channel_id = get_channel_id(channel_id)
    try:
        action = {
            'ActionName': action_name,
            'ScheduleActionStartSettings': {
                'FixedModeScheduleActionStartSettings': {
                    'Time': start_time
                }
            },
            'ScheduleActionSettings': {
                'PauseStateSettings': {
                    'Pipelines': [
                        {
                            'PipelineId': pipeline_id
                        }
                    ]
                }
            }
        }
        
        response = medialive.batch_update_schedule(
            ChannelId=channel_id,
            Creates={'ScheduleActions': [action]}
        )
        
        return f"Created pause action '{action_name}' for pipeline {pipeline_id} in channel {channel_id} at {start_time}"
    except Exception as e:
        return f"Error creating pause action: {str(e)}"

def create_unpause_action(channel_id: Optional[str] = None, action_name: str = "", start_time: str = "", pipeline_id: str = "PIPELINE_0"):
    """Create a pipeline unpause schedule action"""
    channel_id = get_channel_id(channel_id)
    try:
        action = {
            'ActionName': action_name,
            'ScheduleActionStartSettings': {
                'FixedModeScheduleActionStartSettings': {
                    'Time': start_time
                }
            },
            'ScheduleActionSettings': {
                'UnpauseStateSettings': {
                    'Pipelines': [
                        {
                            'PipelineId': pipeline_id
                        }
                    ]
                }
            }
        }
        
        response = medialive.batch_update_schedule(
            ChannelId=channel_id,
            Creates={'ScheduleActions': [action]}
        )
        
        return f"Created unpause action '{action_name}' for pipeline {pipeline_id} in channel {channel_id} at {start_time}"
    except Exception as e:
        return f"Error creating unpause action: {str(e)}"

def delete_schedule_action(channel_id: Optional[str] = None, action_name: str = ""):
    """Delete a schedule action from a MediaLive channel"""
    channel_id = get_channel_id(channel_id)
    try:
        response = medialive.batch_update_schedule(
            ChannelId=channel_id,
            Deletes={'ActionNames': [action_name]}
        )
        
        return f"Deleted schedule action '{action_name}' from channel {channel_id}"
    except Exception as e:
        return f"Error deleting schedule action: {str(e)}"

def create_immediate_input_switch(channel_id: Optional[str] = None, action_name: str = "", input_attachment_name: str = ""):
    """Create an immediate input switch action"""
    channel_id = get_channel_id(channel_id)
    try:
        action = {
            'ActionName': action_name,
            'ScheduleActionStartSettings': {
                'ImmediateModeScheduleActionStartSettings': {}
            },
            'ScheduleActionSettings': {
                'InputSwitchSettings': {
                    'InputAttachmentNameReference': input_attachment_name
                }
            }
        }
        
        response = medialive.batch_update_schedule(
            ChannelId=channel_id,
            Creates={'ScheduleActions': [action]}
        )
        
        return f"Created immediate input switch action '{action_name}' for channel {channel_id}"
    except Exception as e:
        return f"Error creating immediate input switch: {str(e)}"
