from media_ops_contracts.action_result import ActionResult


def test_action_result_round_trips_as_json():
    result = ActionResult(
        approval_id="ap-1",
        action="stop_channel",
        resource_id="1234567",
        before_state="RUNNING",
        after_state="IDLE",
        verified=True,
    )
    assert ActionResult.model_validate_json(result.model_dump_json()) == result
