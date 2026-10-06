"""Typed SCTE-35 structures: only what ad-break diagnosis needs (spec §13)."""

from pydantic import BaseModel, Field

SPLICE_COMMAND_NAMES = {
    0x00: "splice_null",
    0x05: "splice_insert",
    0x06: "time_signal",
    0x07: "bandwidth_reservation",
    0xFF: "private_command",
}

SEGMENTATION_TYPE_NAMES = {
    0x10: "Program Start",
    0x11: "Program End",
    0x20: "Chapter Start",
    0x21: "Chapter End",
    0x22: "Break Start",
    0x23: "Break End",
    0x30: "Provider Advertisement Start",
    0x31: "Provider Advertisement End",
    0x32: "Distributor Advertisement Start",
    0x33: "Distributor Advertisement End",
    0x34: "Provider Placement Opportunity Start",
    0x35: "Provider Placement Opportunity End",
    0x36: "Distributor Placement Opportunity Start",
    0x37: "Distributor Placement Opportunity End",
}


class SegmentationDescriptor(BaseModel):
    event_id: int
    cancel: bool = False
    duration_seconds: float | None = None
    upid_type: int | None = None
    upid_hex: str | None = None
    type_id: int | None = None
    type_name: str | None = None
    segment_num: int | None = None
    segments_expected: int | None = None


class SpliceInsert(BaseModel):
    event_id: int
    cancel: bool = False
    out_of_network: bool | None = None
    splice_immediate: bool | None = None
    splice_pts_seconds: float | None = None
    break_duration_seconds: float | None = None
    auto_return: bool | None = None
    unique_program_id: int | None = None
    avail_num: int | None = None
    avails_expected: int | None = None


class SpliceInfoSection(BaseModel):
    command_type: int
    command_name: str
    pts_adjustment_seconds: float = 0.0
    splice_insert: SpliceInsert | None = None
    time_signal_pts_seconds: float | None = None
    segmentation_descriptors: list[SegmentationDescriptor] = Field(default_factory=list)
    unknown_descriptors_hex: list[str] = Field(default_factory=list)

    @property
    def break_duration_seconds(self) -> float | None:
        if self.splice_insert and self.splice_insert.break_duration_seconds is not None:
            return self.splice_insert.break_duration_seconds
        durations = [
            descriptor.duration_seconds
            for descriptor in self.segmentation_descriptors
            if descriptor.duration_seconds is not None
        ]
        return durations[0] if durations else None
