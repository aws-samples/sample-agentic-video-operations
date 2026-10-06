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
