"""Tag-scoped workflow writes pass only for the app's own signal maps and table."""

import check_synth_iam as gate


def template(*statements):
    document = {"Statement": list(statements)}
    return {
        "Resources": {
            "Policy": {"Type": "AWS::IAM::Policy", "Properties": {"PolicyDocument": document}}
        }
    }


def allow(action, resource="arn:aws:service:us-west-2:111122223333:thing/x"):
    return {"Effect": "Allow", "Action": action, "Resource": resource}


def allow_with_condition(action, condition, resource=None):
    statement = allow(action, resource or gate.SIGNAL_MAP_RESOURCE)
    statement["Condition"] = condition
    return statement


def create_signal_map_condition(value=gate.MANAGED_BY_VALUE):
    return {
        "StringEquals": {"aws:RequestTag/managed-by": value},
        "ForAllValues:StringEquals": {"aws:TagKeys": ["managed-by"]},
    }


def delete_signal_map_condition():
    return {"StringEquals": {"aws:ResourceTag/managed-by": gate.MANAGED_BY_VALUE}}


def workflow_policy_template(*replacements):
    own_table = {"Fn::GetAtt": ["WorkflowTable", "Arn"]}
    statements = [
        allow_with_condition(
            ["medialive:CreateSignalMap", "medialive:CreateTags"],
            create_signal_map_condition(),
        ),
        allow_with_condition(
            ["medialive:GetSignalMap", "medialive:DeleteSignalMap"],
            delete_signal_map_condition(),
        ),
        allow(
            ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan"],
            own_table,
        ),
    ]
    for index, statement in replacements:
        statements[index] = statement
    result = template(*statements)
    result["Resources"]["WorkflowTable"] = {"Type": "AWS::DynamoDB::Table"}
    return result


def test_the_tag_scoped_workflow_policy_passes():
    assert gate.find_iam_problems(workflow_policy_template()) == []


def test_signal_map_create_without_a_condition_fails():
    problems = gate.find_iam_problems(
        workflow_policy_template(
            (
                0,
                allow(
                    ["medialive:CreateSignalMap", "medialive:CreateTags"], gate.SIGNAL_MAP_RESOURCE
                ),
            )
        )
    )
    assert any(
        "CreateSignalMap requires StringEquals aws:RequestTag/managed-by" in p for p in problems
    )
    assert any("CreateTags requires ForAllValues:StringEquals aws:TagKeys" in p for p in problems)


def test_signal_map_create_with_the_wrong_tag_value_fails():
    statement = allow_with_condition(
        ["medialive:CreateSignalMap", "medialive:CreateTags"],
        create_signal_map_condition("another-owner"),
    )
    problems = gate.find_iam_problems(workflow_policy_template((0, statement)))
    assert any(
        "CreateSignalMap requires StringEquals aws:RequestTag/managed-by" in p for p in problems
    )
    assert any("CreateTags requires StringEquals aws:RequestTag/managed-by" in p for p in problems)


def test_signal_map_create_with_only_a_resource_tag_fails():
    statement = allow_with_condition(
        ["medialive:CreateSignalMap", "medialive:CreateTags"],
        delete_signal_map_condition(),
    )
    problems = gate.find_iam_problems(workflow_policy_template((0, statement)))
    assert any(
        "CreateSignalMap requires StringEquals aws:RequestTag/managed-by" in p for p in problems
    )
    assert any(
        "CreateSignalMap requires ForAllValues:StringEquals aws:TagKeys" in p for p in problems
    )


def test_signal_map_delete_without_a_condition_fails():
    statement = allow(
        ["medialive:GetSignalMap", "medialive:DeleteSignalMap"],
        gate.SIGNAL_MAP_RESOURCE,
    )
    problems = gate.find_iam_problems(workflow_policy_template((1, statement)))
    assert any(
        "DeleteSignalMap requires StringEquals aws:ResourceTag/managed-by" in p for p in problems
    )


def test_signal_map_delete_on_star_fails():
    statement = allow_with_condition(
        ["medialive:GetSignalMap", "medialive:DeleteSignalMap"],
        delete_signal_map_condition(),
        "*",
    )
    problems = gate.find_iam_problems(workflow_policy_template((1, statement)))
    assert 'Policy: medialive:DeleteSignalMap on Resource "*"' in problems
    assert any(
        "DeleteSignalMap is not scoped to this stack's signal-map ARN" in p for p in problems
    )


def test_signal_map_create_on_all_medialive_resources_fails():
    every_medialive_resource = {
        "Fn::Sub": ("arn:${AWS::Partition}:medialive:${AWS::Region}:${AWS::AccountId}:*")
    }
    statement = allow_with_condition(
        ["medialive:CreateSignalMap", "medialive:CreateTags"],
        create_signal_map_condition(),
        every_medialive_resource,
    )
    problems = gate.find_iam_problems(workflow_policy_template((0, statement)))
    assert any(
        "CreateSignalMap is not scoped to this stack's signal-map ARN" in p for p in problems
    )
    assert any("CreateTags is not scoped to this stack's signal-map ARN" in p for p in problems)


def test_workflow_put_item_on_another_table_fails():
    other_table = "arn:aws:dynamodb:us-west-2:111122223333:table/other"
    statement = allow(
        ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan"],
        other_table,
    )
    problems = gate.find_iam_problems(workflow_policy_template((2, statement)))
    assert problems == [
        "Policy: dynamodb:PutItem is not scoped to this stack's AWS::DynamoDB::Table"
    ]


def test_start_update_signal_map_is_not_in_the_tag_scoped_class():
    statement = allow_with_condition(
        [
            "medialive:GetSignalMap",
            "medialive:DeleteSignalMap",
            "medialive:StartUpdateSignalMap",
        ],
        delete_signal_map_condition(),
    )
    problems = gate.find_iam_problems(workflow_policy_template((1, statement)))
    assert "Policy: write action medialive:StartUpdateSignalMap in the default synth" in problems
