"""The default-synth IAM gate flags writes and wildcard resources, and nothing it allows."""

import check_synth_iam as gate
import pytest


def template(*statements):
    document = {"Statement": list(statements)}
    return {
        "Resources": {
            "Policy": {"Type": "AWS::IAM::Policy", "Properties": {"PolicyDocument": document}}
        }
    }  # noqa: E501


def allow(action, resource="arn:aws:service:us-west-2:111122223333:thing/x"):
    return {"Effect": "Allow", "Action": action, "Resource": resource}


def test_a_media_write_in_the_default_synth_fails():
    problems = gate.find_iam_problems(template(allow(["medialive:StopChannel"])))
    assert problems == ["Policy: write action medialive:StopChannel in the default synth"]


def test_ecr_pulls_and_reads_pass():
    statements = allow(
        ["ecr:BatchGetImage", "ecr:BatchCheckLayerAvailability", "medialive:DescribeChannel"]
    )  # noqa: E501
    assert gate.find_iam_problems(template(statements)) == []


def test_ecr_push_fails():
    assert "write action ecr:PutImage" in gate.find_iam_problems(template(allow("ecr:PutImage")))[0]


def test_star_resource_is_allowed_only_for_listed_apis():
    problems = gate.find_iam_problems(
        template(allow("medialive:ListChannels", "*"), allow("medialive:DescribeChannel", "*"))
    )
    assert problems == ['Policy: medialive:DescribeChannel on Resource "*"']


def test_wildcard_actions_and_not_action_fail():
    problems = gate.find_iam_problems(
        template(allow("s3:*"), {"Effect": "Allow", "NotAction": "iam:*", "Resource": "*"})
    )
    assert "Policy: s3:* grants every action" in problems
    assert "Policy: NotAction/NotResource is not allowed" in problems


def test_deny_statements_are_ignored():
    deny = {"Effect": "Deny", "Action": "medialive:StopChannel", "Resource": "*"}
    assert gate.find_iam_problems(template(deny)) == []


LOG_GROUP = "arn:aws:logs:us-west-2:111122223333:log-group:/aws/bedrock-agentcore/runtimes/MediaOpsHubRuntime-*"  # noqa: E501
MEMORY = {"Fn::GetAtt": ["HubMemory", "MemoryArn"]}


def test_runtime_telemetry_and_memory_writes_on_their_own_resources_pass():
    statements = (
        allow(["logs:CreateLogGroup", "logs:PutLogEvents"], [LOG_GROUP]),
        allow(["bedrock-agentcore:CreateEvent", "bedrock-agentcore:DeleteMemoryRecord"], MEMORY),
        allow(["cloudwatch:PutMetricData", "xray:PutTraceSegments"], "*"),
    )
    assert gate.find_iam_problems(template(*statements)) == []


def test_the_same_writes_on_star_or_account_wide_scopes_fail():
    every_runtime = (
        "arn:aws:logs:us-west-2:111122223333:log-group:/aws/bedrock-agentcore/runtimes/*"  # noqa: E501
    )
    every_memory = "arn:aws:bedrock-agentcore:us-west-2:111122223333:memory/*"
    problems = gate.find_iam_problems(
        template(
            allow("logs:PutLogEvents", "*"),
            allow("logs:CreateLogGroup", every_runtime),
            allow("bedrock-agentcore:CreateEvent", every_memory),
        )
    )
    assert 'Policy: logs:PutLogEvents on Resource "*"' in problems
    assert (
        "Policy: logs:CreateLogGroup is scoped account-wide, not to this stack's resource"
        in problems
    )  # noqa: E501
    assert (
        "Policy: bedrock-agentcore:CreateEvent is scoped account-wide, not to this stack's resource"
        in problems
    )  # noqa: E501


def test_dynamodb_writes_pass_only_for_a_table_created_by_the_same_stack():
    own_table = {"Fn::GetAtt": ["ResultsTable", "Arn"]}
    own_template = template(allow(["dynamodb:PutItem", "dynamodb:UpdateItem"], own_table))
    own_template["Resources"]["ResultsTable"] = {"Type": "AWS::DynamoDB::Table"}

    assert gate.find_iam_problems(own_template) == []

    other_table = "arn:aws:dynamodb:us-west-2:111122223333:table/other"
    problems = gate.find_iam_problems(template(allow("dynamodb:PutItem", other_table)))
    assert problems == [
        "Policy: dynamodb:PutItem is not scoped to this stack's AWS::DynamoDB::Table"
    ]


@pytest.mark.parametrize("action", sorted(gate.NEVER_GRANT))
def test_workload_identity_token_actions_are_never_granted_even_on_a_scoped_arn(action):
    directory = (
        "arn:aws:bedrock-agentcore:us-west-2:111122223333:workload-identity-directory/default"  # noqa: E501
    )
    [problem] = gate.find_iam_problems(template(allow(action, directory)))
    assert f"{action} is never granted" in problem


@pytest.mark.parametrize("action", sorted(gate.NEVER_ON_STAR))
def test_passing_or_assuming_any_role_fails_but_a_named_role_passes(action):
    [problem] = gate.find_iam_problems(template(allow(action, "*")))
    assert f'{action} on Resource "*"' in problem
    named = "arn:aws:iam::111122223333:role/one-named-role"
    assert gate.find_iam_problems(template(allow(action, named))) == []


@pytest.mark.parametrize("action", ["*", "*:*", "s3:*"])
def test_an_action_wildcard_over_a_whole_service_or_everything_fails(action):
    [problem] = gate.find_iam_problems(template(allow(action)))
    assert "grants every action" in problem


def case_variants(action):
    service, name = action.split(":")
    return [
        action.lower(),
        action.upper(),
        f"{service.upper()}:{name}",
        f"{service}:{name.swapcase()}",
    ]  # noqa: E501


@pytest.mark.parametrize("action", [v for a in sorted(gate.NEVER_GRANT) for v in case_variants(a)])
def test_never_grant_ignores_case(action):
    directory = (
        "arn:aws:bedrock-agentcore:us-west-2:111122223333:workload-identity-directory/default"  # noqa: E501
    )
    [problem] = gate.find_iam_problems(template(allow(action, directory)))
    assert "is never granted" in problem


@pytest.mark.parametrize(
    "action", [v for a in sorted(gate.NEVER_ON_STAR) for v in case_variants(a)]
)
def test_never_on_star_ignores_case(action):
    [problem] = gate.find_iam_problems(template(allow(action, "*")))
    assert 'on Resource "*"' in problem


@pytest.mark.parametrize("action", case_variants("medialive:StopChannel"))
def test_write_verbs_ignore_case(action):
    [problem] = gate.find_iam_problems(template(allow(action)))
    assert "write action" in problem


@pytest.mark.parametrize("action", ["S3:*", "s3:*", "MediaLive:*"])
def test_whole_service_wildcards_ignore_case(action):
    [problem] = gate.find_iam_problems(template(allow(action)))
    assert "grants every action" in problem


@pytest.mark.parametrize("action", ["medialive:Stop*", "MEDIALIVE:stop*", "medialive:StopChanne?"])
def test_partial_wildcards_including_question_mark_fail(action):
    assert any("wildcard action" in p for p in gate.find_iam_problems(template(allow(action))))


def test_case_variants_of_allowed_actions_keep_their_allowance():
    log_group = "arn:aws:logs:us-west-2:111122223333:log-group:/aws/bedrock-agentcore/runtimes/MediaOpsHubRuntime-*"  # noqa: E501
    statements = (
        allow(["LOGS:PutLogEvents"], [log_group]),
        allow(["CloudWatch:putmetricdata"], "*"),
    )
    assert gate.find_iam_problems(template(*statements)) == []
    every_runtime = (
        "arn:aws:logs:us-west-2:111122223333:log-group:/aws/bedrock-agentcore/runtimes/*"  # noqa: E501
    )
    [problem] = gate.find_iam_problems(template(allow("LOGS:CREATELOGGROUP", every_runtime)))
    assert "scoped account-wide" in problem
