"""An AgentCore runtime waits for every policy attached to its role.

The live failure: CREATE_FAILED AgenticIopsRuntime, "Access denied while validating ECR URI …",
because the role's DefaultPolicy (with the ECR pull) was created in the same second.
"""

import check_runtime_dependencies as gate


def template(*, depends_on=None, policy_type="AWS::IAM::Policy", role_ref=None):
    runtime = {
        "Type": "AWS::BedrockAgentCore::Runtime",
        "Properties": {"RoleArn": role_ref or {"Fn::GetAtt": ["ExecutionRole", "Arn"]}},
    }
    if depends_on is not None:
        runtime["DependsOn"] = depends_on
    return {
        "Resources": {
            "ExecutionRole": {"Type": "AWS::IAM::Role", "Properties": {}},
            "ExecutionRoleDefaultPolicy": {
                "Type": policy_type,
                "Properties": {"Roles": [{"Ref": "ExecutionRole"}]},
            },
            "OtherRolePolicy": {
                "Type": "AWS::IAM::Policy",
                "Properties": {"Roles": [{"Ref": "SomeOtherRole"}]},
            },
            "Runtime": runtime,
        }
    }


def test_a_runtime_that_does_not_wait_for_its_role_policy_is_the_race():
    assert gate.find_dependency_problems(template()) == [
        "Runtime can be created before ExecutionRoleDefaultPolicy, a policy on its role "
        "ExecutionRole: add it to the runtime's DependsOn"
    ]


def test_a_managed_policy_attached_to_the_role_counts_too():
    assert gate.find_dependency_problems(template(policy_type="AWS::IAM::ManagedPolicy"))


def test_depending_on_the_policy_passes_as_a_string_or_a_list():
    assert gate.find_dependency_problems(template(depends_on="ExecutionRoleDefaultPolicy")) == []
    assert gate.find_dependency_problems(template(depends_on=["ExecutionRoleDefaultPolicy"])) == []


def test_a_role_from_outside_the_stack_and_other_roles_policies_are_not_flagged():
    external = "arn:aws:iam::111122223333:role/ExistingRole"
    assert gate.find_dependency_problems(template(role_ref=external)) == []
    only_other = template(depends_on=["ExecutionRoleDefaultPolicy"])
    assert gate.find_dependency_problems(only_other) == []  # OtherRolePolicy isn't on its role


def test_a_ref_to_the_role_is_read_like_a_get_att():
    assert gate.find_dependency_problems(template(role_ref={"Ref": "ExecutionRole"}))


# The shapes CDK synthesizes for `Role.fromRoleArn(..., {mutable: true})` plus
# `repository.grantPull(role)` (checked with a real synth): the grant
# is an in-stack policy that names the role, while the runtime holds the role's ARN.
ECR_PULL = {
    "Statement": [{"Action": "ecr:GetAuthorizationToken", "Effect": "Allow", "Resource": "*"}]
}


def imported_role_template(role_arn, policy_roles, *, depends_on=None, parameters=None):
    runtime = {"Type": "AWS::BedrockAgentCore::Runtime", "Properties": {"RoleArn": role_arn}}
    if depends_on is not None:
        runtime["DependsOn"] = depends_on
    resources = {"Runtime": runtime}
    if policy_roles is not None:
        resources["ImportedPolicy6F5EAEFA"] = {
            "Type": "AWS::IAM::Policy",
            "Properties": {
                "PolicyDocument": ECR_PULL,
                "PolicyName": "ImportedPolicy6F5EAEFA",
                "Roles": policy_roles,
            },
        }
    return {"Parameters": parameters or {}, "Resources": resources}


LITERAL_ARN = "arn:aws:iam::111122223333:role/existing-runtime-role"
JOINED_ARN = {
    "Fn::Join": [
        "",
        [
            "arn:",
            {"Ref": "AWS::Partition"},
            ":iam::",
            {"Ref": "AWS::AccountId"},
            ":role/",
            {"Ref": "RoleName"},
        ],
    ]
}


def test_a_mutable_imported_role_named_literally_is_the_same_race():
    template = imported_role_template(LITERAL_ARN, ["existing-runtime-role"])
    assert gate.find_dependency_problems(template) == [
        "Runtime can be created before ImportedPolicy6F5EAEFA, a policy on its role "
        "existing-runtime-role: add it to the runtime's DependsOn"
    ]
    waiting = imported_role_template(
        LITERAL_ARN, ["existing-runtime-role"], depends_on=["ImportedPolicy6F5EAEFA"]
    )
    assert gate.find_dependency_problems(waiting) == []


def test_a_role_path_is_not_part_of_the_name_a_policy_uses():
    with_path = "arn:aws:iam::111122223333:role/service/existing-runtime-role"
    assert gate.find_dependency_problems(
        imported_role_template(with_path, ["existing-runtime-role"])
    )


def test_an_imported_role_named_by_a_parameter_is_matched_through_join_or_sub():
    parameters = {"RoleName": {"Type": "String"}}
    joined = imported_role_template(JOINED_ARN, [{"Ref": "RoleName"}], parameters=parameters)
    assert gate.find_dependency_problems(joined) == [
        "Runtime can be created before ImportedPolicy6F5EAEFA, a policy on its role "
        "named by parameter RoleName: add it to the runtime's DependsOn"
    ]
    subbed = {"Fn::Sub": "arn:${AWS::Partition}:iam::${AWS::AccountId}:role/${RoleName}"}
    assert gate.find_dependency_problems(
        imported_role_template(subbed, [{"Ref": "RoleName"}], parameters=parameters)
    )


def test_a_policy_that_cannot_be_ruled_out_for_an_imported_role_is_flagged():
    parameters = {"RoleArn": {"Type": "String"}, "OtherName": {"Type": "String"}}
    split = {"Fn::Select": [1, {"Fn::Split": ["/", {"Ref": "RoleArn"}]}]}
    whole_arn = imported_role_template({"Ref": "RoleArn"}, [split], parameters=parameters)
    assert gate.find_dependency_problems(whole_arn) == [
        "Runtime can be created before ImportedPolicy6F5EAEFA, which may be a policy on its "
        "imported role: add it to the runtime's DependsOn"
    ]
    other_parameter = imported_role_template(
        LITERAL_ARN, [{"Ref": "OtherName"}], parameters=parameters
    )
    assert gate.find_dependency_problems(other_parameter)  # it may hold the same name


def test_an_imported_role_with_no_policy_in_the_stack_or_another_named_role_passes():
    assert gate.find_dependency_problems(imported_role_template(LITERAL_ARN, None)) == []
    assert gate.find_dependency_problems(imported_role_template(LITERAL_ARN, ["other-role"])) == []
