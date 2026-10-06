"""Build the MediaLive schedule-action body for one approved create action (pure)."""

from media_ops_contracts.tool_failure import FailureKind, ToolFailure

_REQUIRED_PARAMETERS = {
    "create_input_switch_action": ("action_name", "input_attachment", "start_time"),
    "create_scte35_action": ("action_name", "start_time", "splice_event_id"),
    "create_pause_action": ("action_name", "start_time", "pipeline_id"),
    "create_unpause_action": ("action_name", "start_time", "pipeline_id"),
    "switch_channel_input": ("action_name", "input_attachment"),
}
SCHEDULE_CREATE_ACTIONS = frozenset(_REQUIRED_PARAMETERS)


def build_schedule_action(action: str, parameters: dict[str, str]) -> dict:
    """Return the ScheduleActions entry for `action`, or raise InvalidRequest."""
    missing = [name for name in _REQUIRED_PARAMETERS.get(action, ()) if not parameters.get(name)]
    if action not in _REQUIRED_PARAMETERS or missing:
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            f"{action} needs parameters: {', '.join(missing) or 'unknown action'}",
            f"Provide {', '.join(_REQUIRED_PARAMETERS.get(action, ('a known action',)))}.",
        )
    return {
        "ActionName": parameters["action_name"],
        "ScheduleActionStartSettings": _start_settings(parameters),
        "ScheduleActionSettings": _action_settings(action, parameters),
    }


def _start_settings(parameters: dict[str, str]) -> dict:
    if parameters.get("start_time"):
        return {"FixedModeScheduleActionStartSettings": {"Time": parameters["start_time"]}}
    return {"ImmediateModeScheduleActionStartSettings": {}}


def _action_settings(action: str, parameters: dict[str, str]) -> dict:
    if action in ("create_input_switch_action", "switch_channel_input"):
        reference = parameters["input_attachment"]
        return {"InputSwitchSettings": {"InputAttachmentNameReference": reference}}
    if action == "create_scte35_action":
        splice = {"SpliceEventId": int(parameters["splice_event_id"])}
        if parameters.get("duration"):
            splice["Duration"] = int(parameters["duration"])
        return {"Scte35SpliceInsertSettings": splice}
    state = "PauseStateSettings" if action == "create_pause_action" else "UnpauseStateSettings"
    return {state: {"Pipelines": [{"PipelineId": parameters["pipeline_id"]}]}}
