"""Which MediaLive CloudWatch metrics belong to which health category."""

CATEGORY_METRICS: dict[str, tuple[str, ...]] = {
    "channel_health": (
        "ActiveAlerts", "PipelinesLocked", "InputVideoAligned", "FillMsec",
        "InputVideoFrameRate", "DroppedFrames", "SvqTime",
    ),
    "input_health": (
        "NetworkIn", "InputLossSeconds", "InputVideoFrameRate", "RtpPacketsReceived",
        "RtpPacketsLost", "RtpPacketsRecoveredViaFec", "FecRowPacketsReceived",
        "FecColumnPacketsReceived", "ChannelInputErrorSeconds", "PrimaryInputActive",
    ),
    "output_health": (
        "NetworkOut", "ActiveOutputs", "Output4xxErrors", "Output5xxErrors",
        "OutputAudioLevelDbfs", "OutputAudioLevelLkfs", "ComplexFrcPresent", "DroppedFrames",
        "SvqTime",
    ),
    "media_health": (
        "InputTimecodesPresent", "OutputAudioLevelDbfs", "OutputAudioLevelLkfs",
        "ChannelInputErrorSeconds", "FillMsec",
    ),
    "content_quality": (
        "MinMQCS", "MqcsBlackFrameDetected", "MqcsFreezeFrameDetected",
        "MqcsContinuityCounterErrors", "FillMsec", "InputLossSeconds", "DroppedFrames",
    ),
}  # fmt: skip

# The short list `read_channel_metrics` shows when no category is given.
SUMMARY_METRICS = (
    "ActiveAlerts", "InputLossSeconds", "InputVideoFrameRate", "OutputVideoFrameRate",
    "NetworkIn", "NetworkOut", "FillMsec", "ActiveInputFailoverCount", "DroppedFrames",
)  # fmt: skip

# Series included in the chart table, per category.
TABLE_METRICS: dict[str, tuple[str, ...]] = {
    "channel_health": ("ActiveAlerts", "FillMsec", "DroppedFrames"),
    "input_health": ("NetworkIn", "InputLossSeconds", "RtpPacketsLost"),
    "output_health": ("NetworkOut", "Output4xxErrors", "Output5xxErrors"),
    "media_health": ("ChannelInputErrorSeconds", "FillMsec"),
    "content_quality": ("MqcsBlackFrameDetected", "MqcsFreezeFrameDetected", "InputLossSeconds"),
}

ALL_METRICS = tuple(dict.fromkeys(m for metrics in CATEGORY_METRICS.values() for m in metrics))

# The statistic AWS recommends per metric (MediaLive user guide, "CloudWatch metrics"). A
# 5-minute Sum of InputLossSeconds is the seconds lost in that period; an Average is not.
STATISTIC_BY_METRIC: dict[str, str] = {
    "ActiveAlerts": "Maximum",
    "InputLossSeconds": "Sum",
    "ChannelInputErrorSeconds": "Sum",
    "RtpPacketsLost": "Sum",
    "RtpPacketsReceived": "Sum",
    "RtpPacketsRecoveredViaFec": "Sum",
    "FecRowPacketsReceived": "Sum",
    "FecColumnPacketsReceived": "Sum",
    "InputVideoFrameRate": "Maximum",
    "PrimaryInputActive": "Minimum",
    "PipelinesLocked": "Minimum",
    "InputTimecodesPresent": "Minimum",
    "FillMsec": "Maximum",
    "DroppedFrames": "Sum",
    "SvqTime": "Maximum",
    "ComplexFrcPresent": "Maximum",
    "ActiveOutputs": "Minimum",
    "Output4xxErrors": "Sum",
    "Output5xxErrors": "Sum",
    "MinMQCS": "Minimum",
    # AWS lists Minimum or Maximum; Minimum shows a silent or dropped audio track.
    "OutputAudioLevelDbfs": "Minimum",
    "OutputAudioLevelLkfs": "Minimum",
    "MqcsBlackFrameDetected": "Minimum",
    "MqcsFreezeFrameDetected": "Minimum",
    "MqcsContinuityCounterErrors": "Minimum",
}
DEFAULT_STATISTIC = "Average"

# The dimension set MediaLive publishes each metric with (same reference). Querying any other
# set returns no datapoints. OutputGroupName and AudioDescriptionName take every name the
# channel defines; DroppedFrames and SvqTime are published per pipeline and Region only.
CHANNEL_DIMENSIONS = ("ChannelId", "Pipeline")
DIMENSIONS_BY_METRIC: dict[str, tuple[str, ...]] = {
    "MinMQCS": ("ChannelId", "Pipeline", "OutputGroupName"),
    "ActiveOutputs": ("ChannelId", "Pipeline", "OutputGroupName"),
    "Output4xxErrors": ("ChannelId", "Pipeline", "OutputGroupName"),
    "Output5xxErrors": ("ChannelId", "Pipeline", "OutputGroupName"),
    "OutputAudioLevelDbfs": ("ChannelId", "Pipeline", "AudioDescriptionName"),
    "OutputAudioLevelLkfs": ("ChannelId", "Pipeline", "AudioDescriptionName"),
    "DroppedFrames": ("Pipeline", "Region"),
    "SvqTime": ("Pipeline", "Region"),
}

# Dimensions whose values come from the channel's configuration, one query per value.
CHANNEL_CONFIGURED_DIMENSIONS = frozenset({"OutputGroupName", "AudioDescriptionName"})
