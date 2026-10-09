"""The IAM gate's wildcard, case, shape and condition blind spots, hunted.

Every planted template below grants something the default synth must not, in a form a
literal-minded check could miss. Each must give at least one problem. The last test pins
the stack's real statement shapes, so a fix can't refuse what the stack needs.
"""

import check_synth_iam as gate
import pytest

ARN = "arn:aws:service:us-west-2:111122223333:thing/x"
OWN_TABLE = {"Fn::GetAtt": ["WorkflowTable", "Arn"]}
OTHER_TABLE = "arn:aws:dynamodb:us-west-2:111122223333:table/someone-elses"


def policy(*statements, resource_type="AWS::IAM::Policy", extra=None):
    resources = {
        "Policy": {
            "Type": resource_type,
            "Properties": {"PolicyDocument": {"Statement": list(statements)}},
        },
        "WorkflowTable": {"Type": "AWS::DynamoDB::Table", "Properties": {}},
    }
    return {"Resources": resources | (extra or {})}


def inline(resource_type, *statements):
    """A policy document inside a role, user or group's own `Policies` list."""
    document = {"PolicyName": "inline", "PolicyDocument": {"Statement": list(statements)}}
    return {
        "Resources": {"Principal": {"Type": resource_type, "Properties": {"Policies": [document]}}}
    }


def allow(action, resource=ARN, **more):
    return {"Effect": "Allow", "Action": action, "Resource": resource} | more


def signal_map_statement(condition):
    return allow("medialive:CreateSignalMap", gate.SIGNAL_MAP_RESOURCE, Condition=condition)


def signal_map_write(condition):
    return policy(signal_map_statement(condition))


TAG_KEYS = {"ForAllValues:StringEquals": {"aws:TagKeys": ["managed-by"]}}
REQUEST_TAG = {"aws:RequestTag/managed-by": gate.MANAGED_BY_VALUE}

PLANTED = {
    # Wildcard actions that a literal write-verb match would not see.
    "wildcard medialive:Start*": policy(allow("medialive:Start*")),
    "wildcard medialive:*Channel": policy(allow("medialive:*Channel")),
    "wildcard mediaconnect:*": policy(allow("mediaconnect:*")),
    "wildcard *:Put*": policy(allow("*:Put*")),
    "wildcard iam:Pass*": policy(allow("iam:Pass*", "*")),
    "wildcard GetWorkloadAccessToken*": policy(allow("bedrock-agentcore:GetWorkloadAccessToken*")),
    "wildcard with ?": policy(allow("medialive:St?rtChannel")),
    # Case: IAM action names are case-insensitive.
    "case MediaLive:StartChannel": policy(allow("MediaLive:StartChannel")),
    "case IAM:PassRole on *": policy(allow("IAM:PassRole", "*")),
    "case Bedrock-AgentCore never-grant": policy(
        allow("Bedrock-AgentCore:GetWorkloadAccessTokenForUserId")
    ),
    "case DynamoDB:PutItem on another table": policy(allow("DynamoDB:PutItem", OTHER_TABLE)),
    "case Logs:CreateLogGroup account-wide": policy(
        allow("Logs:CreateLogGroup", "arn:aws:logs:us-west-2:111122223333:log-group:*")
    ),
    # Shape.
    "NotAction": policy({"Effect": "Allow", "NotAction": "iam:*", "Resource": ARN}),
    "NotResource": policy(
        {"Effect": "Allow", "Action": "medialive:DescribeChannel", "NotResource": ARN}
    ),
    "Effect chosen by Fn::If": policy(
        {
            "Effect": {"Fn::If": ["Prod", "Allow", "Deny"]},
            "Action": "medialive:StopChannel",
            "Resource": ARN,
        }
    ),
    "Effect missing": policy({"Action": "medialive:StopChannel", "Resource": ARN}),
    "Action as one string": policy(allow("medialive:StopChannel")),
    "Action built by an intrinsic": policy(
        allow({"Fn::Split": [",", "medialive:StopChannel,medialive:StartChannel"]})
    ),
    "Statement chosen by Fn::If": policy(
        {"Fn::If": ["Prod", allow("medialive:StopChannel"), {"Ref": "AWS::NoValue"}]}
    ),
    "inline policy of a role": inline("AWS::IAM::Role", allow("medialive:StopChannel")),
    "inline policy of a user": inline("AWS::IAM::User", allow("medialive:StopChannel")),
    "inline policy of a group": inline("AWS::IAM::Group", allow("medialive:StopChannel")),
    "AWS::IAM::RolePolicy": policy(
        allow("medialive:StopChannel"), resource_type="AWS::IAM::RolePolicy"
    ),
    "AWS::IAM::UserPolicy": policy(
        allow("medialive:StopChannel"), resource_type="AWS::IAM::UserPolicy"
    ),
    "AWS::IAM::GroupPolicy": policy(
        allow("medialive:StopChannel"), resource_type="AWS::IAM::GroupPolicy"
    ),
    "an AWS managed policy attached to a role": {
        "Resources": {
            "Role": {
                "Type": "AWS::IAM::Role",
                "Properties": {
                    "ManagedPolicyArns": ["arn:aws:iam::aws:policy/AdministratorAccess"]
                },
            }
        }
    },
    "Resource Fn::Join collapsing to *": policy(
        allow("medialive:DescribeChannel", {"Fn::Join": ["", ["*"]]})
    ),
    "Resource Fn::Sub collapsing to *": policy(
        allow("medialive:DescribeChannel", {"Fn::Sub": "*"})
    ),
    "Resource list hiding *": policy(allow("medialive:DescribeChannel", [ARN, "*"])),
    # Conditions on the tag-scoped class.
    "tag condition StringLike": signal_map_write({"StringLike": REQUEST_TAG} | TAG_KEYS),
    "tag condition IfExists": signal_map_write({"StringEqualsIfExists": REQUEST_TAG} | TAG_KEYS),
    "TagKeys ForAnyValue": signal_map_write(
        {"StringEquals": REQUEST_TAG, "ForAnyValue:StringEquals": {"aws:TagKeys": ["managed-by"]}}
    ),
    "TagKeys with an extra key": signal_map_write(
        {
            "StringEquals": REQUEST_TAG,
            "ForAllValues:StringEquals": {"aws:TagKeys": ["managed-by", "owner"]},
        }
    ),
    "Null instead of StringEquals": signal_map_write(
        {"Null": {"aws:RequestTag/managed-by": "false"}} | TAG_KEYS
    ),
    "tag value as a list with *": signal_map_write(
        {"StringEquals": {"aws:RequestTag/managed-by": [gate.MANAGED_BY_VALUE, "*"]}} | TAG_KEYS
    ),
    "tag-scoped write on every signal map in any account": policy(
        allow(
            "medialive:CreateSignalMap",
            "arn:aws:medialive:*:*:signal-map:*",
            Condition={"StringEquals": REQUEST_TAG} | TAG_KEYS,
        )
    ),
}


@pytest.mark.parametrize("label", sorted(PLANTED))
def test_a_planted_grant_is_refused(label):
    assert gate.find_iam_problems(PLANTED[label]) != [], label


def test_the_stack_s_own_statement_shapes_still_pass():
    """What the real synth contains: these must stay clean after every fix above."""
    template = policy(
        allow(["ecr:BatchGetImage", "medialive:DescribeChannel"], [ARN]),
        allow("medialive:ListChannels", "*"),
        allow(["dynamodb:PutItem", "dynamodb:GetItem"], OWN_TABLE),
        signal_map_statement({"StringEquals": REQUEST_TAG} | TAG_KEYS),
        {"Effect": "Deny", "Action": "medialive:StopChannel", "Resource": "*"},
        resource_type="AWS::IAM::ManagedPolicy",
    )
    assert gate.find_iam_problems(template) == []
