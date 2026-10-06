"""Typed MediaLive results returned by the media_live adapters."""

from enum import StrEnum

from pydantic import BaseModel


class ChannelState(StrEnum):
    CREATING = "CREATING"
    CREATE_FAILED = "CREATE_FAILED"
    IDLE = "IDLE"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    RECOVERING = "RECOVERING"
    STOPPING = "STOPPING"
    DELETING = "DELETING"
    DELETED = "DELETED"
    UPDATING = "UPDATING"
    UPDATE_FAILED = "UPDATE_FAILED"


class ChannelSummary(BaseModel):
    channel_id: str
    name: str
    state: ChannelState
    pipelines_running: int = 0


class PipelineDetail(BaseModel):
    pipeline_id: str
    active_input_attachment: str | None = None


class ChannelDetails(ChannelSummary):
    channel_class: str | None = None
    output_locking_mode: str | None = None
    input_attachments: list[str] = []
    output_groups: list[str] = []
    audio_descriptions: list[str] = []
    pipelines: list[PipelineDetail] = []


class ScheduleActionSummary(BaseModel):
    action_name: str
    action_type: str
    start: str
    input_attachment: str | None = None
