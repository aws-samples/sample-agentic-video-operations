import json
import re
import sys
import types
from pathlib import Path
from textwrap import dedent

import pytest

TEMPLATE = Path("samples/cmcd/cloudfront-cmcd-kinesis.yaml")


def template_text() -> str:
    return TEMPLATE.read_text()


def inline_lambda(resource: str) -> str:
    lines = template_text().splitlines()
    resource_start = lines.index(f"  {resource}:")
    zip_start = next(
        index
        for index in range(resource_start, len(lines))
        if lines[index].startswith("        ZipFile:")
    )
    code: list[str] = []
    for line in lines[zip_start + 1 :]:
        if line and len(line) - len(line.lstrip()) <= 6:
            break
        code.append(line)
    return dedent("\n".join(code))


def test_inline_token_and_processor_lambdas_are_valid_python():
    compile(inline_lambda("UpdateSecretLambda"), "UpdateSecretLambda", "exec")
    compile(inline_lambda("CMCDProcessorLambda"), "CMCDProcessorLambda", "exec")


def test_template_provisions_bucket_scoped_read_and_write_tokens():
    template = template_text()

    assert 'READ_DESCRIPTION = "cmcd-mcp-server read-only"' in template
    assert 'WRITE_DESCRIPTION = "cmcd-kinesis-processor write-only"' in template
    assert "find_or_create_token(" in template
    assert '"read",' in template
    assert '"write",' in template
    assert "cmcd_deploy_smoke" in template
    assert "${AWS::StackName}-token-${AWS::AccountId}" not in template


def test_template_parameterizes_the_smallest_supported_influx_and_bastion_classes():
    template = template_text()
    parameters = template.split("Parameters:", 1)[1].split("Resources:", 1)[0]
    influx = parameters.split("  InfluxDBInstanceType:", 1)[1].split("  BastionInstanceType:", 1)[0]
    bastion = parameters.split("  BastionInstanceType:", 1)[1]
    instance = template.split("  InfluxDBInstance:", 1)[1].split("  # VPC for InfluxDB", 1)[0]
    bastion_host = template.split("  NewBastionHost:", 1)[1].split(
        "  # Managed Policy for Lambda VPC access", 1
    )[0]

    assert "Default: db.influx.medium" in influx
    assert "- db.influx.medium" in influx
    assert "DbInstanceType: !Ref InfluxDBInstanceType" in instance
    assert "Default: t3.nano" in bastion
    assert "InstanceType: !Ref BastionInstanceType" in bastion_host


def test_named_stream_log_config_and_processor_are_stack_prefixed():
    template = template_text()

    assert "Name: !Sub '${AWS::StackName}-${KinesisStreamName}'" in template
    assert "Name: !Sub '${AWS::StackName}-cmcd-realtime-logs'" in template
    assert "FunctionName: !Sub '${AWS::StackName}-cmcd-kinesis-processor'" in template
    assert "FunctionName: !Sub '${AWS::StackName}-deploy-index-html'" in template


def test_cloudfront_uses_the_caching_optimized_managed_policy():
    distribution = (
        template_text()
        .split("  CMCDCloudFrontDistribution:", 1)[1]
        .split("  # InfluxDB Password Secret", 1)[0]
    )

    assert "CachePolicyId: 658327ea-f89d-4fab-a63d-7e88639e58f6  # CachingOptimized" in distribution
    assert "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" not in distribution


def test_processor_reads_write_token_from_the_scoped_secret():
    template = template_text()
    processor = template.split("  CMCDProcessorLambda:", 1)[1].split("  # Event Source Mapping", 1)[
        0
    ]
    role = template.split("  LambdaExecutionRole:", 1)[1].split("  # Lambda Function", 1)[0]

    assert "INFLUXDB_SECRET_ARN: !Ref InfluxDBProcessorSecret" in processor
    assert 'secret["writeToken"]' in processor
    assert "INFLUXDB_TOKEN:" not in processor
    assert "- secretsmanager:GetSecretValue" in role
    assert "Resource: !Ref InfluxDBProcessorSecret" in role
    assert "Resource: !Ref InfluxDBSecret" not in role


def test_processor_drops_only_non_positive_cmcd_placeholders():
    namespace = {}
    exec(inline_lambda("CMCDProcessorLambda"), namespace)  # noqa: S102

    parsed = namespace["parse_cmcd_value"]("br=0,d=-1,mtp=4800,pr=0,rtp=0,tb=-10,v=0,bl=0,dl=0,bs")

    assert parsed == {
        "mtp": "4800",
        "bl": "0",
        "dl": "0",
        "bs": True,
    }


def test_token_provisioner_bounds_retries_and_always_uses_a_stable_identity():
    template = template_text()
    provisioner = inline_lambda("UpdateSecretLambda")
    custom_resource = template.split("  UpdateSecretCustomResource:", 1)[1].split(
        "  # IAM Role for Secret Rotation", 1
    )[0]

    assert "context.get_remaining_time_in_millis()" in provisioner
    assert "except HTTPError as error:" in provisioner
    assert "InfluxDB authentication failed with HTTP 401" in provisioner
    assert "if not 500 <= error.code < 600:" in provisioner
    assert "attempts=3" in provisioner
    assert "except (URLError, TimeoutError)" in provisioner
    assert "physicalResourceId=PHYSICAL_RESOURCE_ID" in provisioner
    assert "ServiceTimeout: 300" in custom_resource
    assert "Timeout: 240" in template
    assert "Bucket: !Ref TableName" in custom_resource
    assert "for attempt in range(5):" in provisioner
    assert 'secret_dict.pop("writeToken", None)' in provisioner


def test_template_outputs_the_configured_influxdb_bucket_name():
    outputs = template_text().split("Outputs:", 1)[1]

    assert "InfluxDBBucketName:" in outputs
    assert "Value: !Ref TableName" in outputs


def test_token_custom_resource_keeps_an_s3_response_path_until_delete_finishes():
    template = template_text()
    endpoint = template.split("  S3GatewayEndpoint:", 1)[1].split(
        "  PrivateSubnet1RouteTableAssociation:", 1
    )[0]
    custom_resource = template.split("  UpdateSecretCustomResource:", 1)[1].split(
        "  # IAM Role for Secret Rotation", 1
    )[0]

    assert "Type: AWS::EC2::VPCEndpoint" in endpoint
    assert "VpcEndpointType: Gateway" in endpoint
    assert "ServiceName: !Sub 'com.amazonaws.${AWS::Region}.s3'" in endpoint
    assert "RouteTableIds:\n        - !Ref PrivateRouteTable" in endpoint
    for dependency in (
        "PrivateSubnet1RouteTableAssociation",
        "PrivateSubnet2RouteTableAssociation",
        "S3GatewayEndpoint",
        "SecretsManagerEndpoint",
    ):
        assert f"      - {dependency}" in custom_resource


def test_s3_gateway_endpoint_allows_only_response_and_stack_bucket_access():
    endpoint = (
        template_text()
        .split("  S3GatewayEndpoint:", 1)[1]
        .split("  PrivateSubnet1RouteTableAssociation:", 1)[0]
    )

    assert "PolicyDocument:" in endpoint
    assert "cloudformation-custom-resource-response-${RegionWithoutDashes}/*" in endpoint
    assert "Fn::Split:" in endpoint
    assert "- !Ref AWS::Region" in endpoint
    assert "- !GetAtt ContentBucket.Arn" in endpoint
    assert "DeploymentArtifactsBucketName" not in endpoint
    actions = set(re.findall(r"(?:Action:|-) (s3:[A-Za-z]+)", endpoint))
    assert actions == {
        "s3:DeleteObject",
        "s3:GetBucketLocation",
        "s3:GetObject",
        "s3:ListBucket",
        "s3:PutObject",
    }
    assert endpoint.count("Resource:") == 3
    assert endpoint.count("cloudformation-custom-resource-response-") == 1
    assert endpoint.count("ContentBucket") == 2
    assert "Action: '*'" not in endpoint
    assert "Resource: '*'" not in endpoint


def test_console_launch_has_no_required_parameters():
    parameters = template_text().split("Parameters:", 1)[1].split("Resources:", 1)[0]
    declarations = re.split(r"(?m)^  (?=[A-Z][A-Za-z0-9]+:\n)", parameters)

    assert declarations[0].strip() == ""
    assert all("\n    Default:" in declaration for declaration in declarations[1:])


def test_s3_gateway_endpoint_scopes_stack_buckets_to_this_account():
    endpoint = (
        template_text()
        .split("  S3GatewayEndpoint:", 1)[1]
        .split("  PrivateSubnet1RouteTableAssociation:", 1)[0]
    )
    response = endpoint.split("Sid: SendCloudFormationCustomResourceResponse", 1)[1].split(
        "Sid: ReadStackBucketMetadata", 1
    )[0]
    metadata = endpoint.split("Sid: ReadStackBucketMetadata", 1)[1].split(
        "Sid: AccessStackBucketObjects", 1
    )[0]
    objects = endpoint.split("Sid: AccessStackBucketObjects", 1)[1]
    account_condition = (
        "Condition:\n"
        "              StringEquals:\n"
        "                aws:PrincipalAccount: !Sub '${AWS::AccountId}'"
    )

    assert "Condition:" not in response
    assert account_condition in metadata
    assert account_condition in objects
    assert endpoint.count("aws:PrincipalAccount") == 2


def test_private_lambdas_use_a_two_az_secrets_endpoint_instead_of_a_nat_gateway():
    template = template_text()
    endpoint = template.split("  SecretsManagerEndpoint:", 1)[1].split(
        "  # Security Group for Bastion Host", 1
    )[0]
    endpoint_security_group = template.split("  SecretsManagerEndpointSecurityGroup:", 1)[1].split(
        "  SecretsManagerEndpoint:", 1
    )[0]

    assert "AWS::EC2::NatGateway" not in template
    assert "NatGatewayId:" not in template
    assert "NATGatewayEIP:" not in template
    assert "VpcEndpointType: Interface" in endpoint
    assert "com.amazonaws.${AWS::Region}.secretsmanager" in endpoint
    assert "PrivateDnsEnabled: true" in endpoint
    assert endpoint.count("- !Ref PrivateSubnet") == 2
    assert "- !Ref SecretsManagerEndpointSecurityGroup" in endpoint
    assert "- secretsmanager:GetSecretValue" in endpoint
    assert "- secretsmanager:UpdateSecret" in endpoint
    assert "- !Ref InfluxDBSecret" in endpoint
    assert "- !Ref InfluxDBProcessorSecret" in endpoint
    assert "aws:PrincipalAccount: !Ref AWS::AccountId" in endpoint
    assert "SourceSecurityGroupId: !Ref LambdaSecurityGroup" in endpoint_security_group


def test_token_custom_resource_delete_returns_success_before_influxdb_work():
    provisioner = inline_lambda("UpdateSecretLambda")

    delete_start = provisioner.index('if event["RequestType"] == "Delete":')
    create_start = provisioner.index("secrets_client = boto3.client('secretsmanager')")
    assert delete_start < create_start
    assert '{"TokensProvisioned": False}' in provisioner
    assert "return\n    try:" in provisioner


def test_processor_write_has_an_explicit_timeout():
    processor = inline_lambda("CMCDProcessorLambda")

    assert "timeout=urllib3.Timeout(connect=5, read=10)" in processor


def test_processor_failures_retry_and_reach_the_dlq():
    template = template_text()
    mapping = template.split("  KinesisEventSourceMapping:", 1)[1].split(
        "  # IAM Role for Index HTML", 1
    )[0]
    processor = template.split("  CMCDProcessorLambda:", 1)[1].split("  # Event Source Mapping", 1)[
        0
    ]

    handler = processor.split("          def parse_cloudfront_log", 1)[0].split(
        "          def lambda_handler", 1
    )[1]
    assert "error_count" not in handler
    assert "for record in event['Records']:\n                      try:" not in handler
    assert "raise" in handler
    assert "BisectBatchOnFunctionError: true" in mapping
    assert "MaximumRetryAttempts: 3" in mapping
    assert "MaximumRecordAgeInSeconds: 3600" in mapping
    assert "Destination: !GetAtt LambdaDLQ.Arn" in mapping
    assert "- sqs:SendMessage" in template


def test_bastion_script_never_reads_or_prints_the_password():
    template = template_text()
    bastion = template.split("  NewBastionHost:", 1)[1].split(
        "  # Managed Policy for Lambda VPC access", 1
    )[0]

    assert "get-secret-value" not in bastion
    assert "PASSWORD=" not in bastion
    assert "Password:" not in bastion
    assert "-password" not in bastion


class FakeInfluxAuthorizations:
    """An InfluxDB /api/v2/authorizations endpoint whose POST responses can be lost."""

    def __init__(self, post_outcomes):
        self.tokens = []
        self.post_outcomes = list(post_outcomes)
        self.posts = 0

    def open(self, request, timeout):
        from urllib.error import HTTPError, URLError

        if request.get_method() == "GET":
            body = {"authorizations": self.tokens}
            return FakeResponse(200, json.dumps(body).encode())
        self.posts += 1
        outcome = self.post_outcomes.pop(0)
        if outcome == "http-503":
            raise HTTPError(request.full_url, 503, "unavailable", {}, None)
        if outcome == "http-400":
            raise HTTPError(request.full_url, 400, "bad request", {}, None)
        created = json.loads(request.data) | {"token": f"token-{self.posts}"}
        self.tokens.append(created)
        if outcome == "created-but-response-lost":
            raise URLError("connection reset")
        return FakeResponse(201, json.dumps(created).encode())


class FakeResponse:
    def __init__(self, status, body):
        self.status, self.body = status, body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.body


def token_provisioner(monkeypatch):
    monkeypatch.setitem(sys.modules, "cfnresponse", types.ModuleType("cfnresponse"))
    namespace: dict = {}
    exec(inline_lambda("UpdateSecretLambda"), namespace)  # noqa: S102 - the template's own code
    # The template's own `time` is the real module: patch it for this test only, or every
    # later test in the process would sleep for no time at all.
    monkeypatch.setattr(namespace["time"], "sleep", lambda _: None)
    return namespace


def create_token(namespace, endpoint_api):
    context = types.SimpleNamespace(get_remaining_time_in_millis=lambda: 200_000)
    return namespace["find_or_create_token"](
        endpoint_api, "https://influx.example.com", "org-1", "bucket-1",
        "cmcd-mcp-server read-only", "read", context,
    )  # fmt: skip


def test_a_lost_token_response_is_found_by_description_not_created_twice(monkeypatch):
    api = FakeInfluxAuthorizations(["created-but-response-lost"])

    token = create_token(token_provisioner(monkeypatch), api)

    assert token == "token-1"
    assert api.posts == 1
    assert len(api.tokens) == 1


def test_a_server_error_on_create_retries_after_a_fresh_lookup(monkeypatch):
    api = FakeInfluxAuthorizations(["http-503", "created"])

    assert create_token(token_provisioner(monkeypatch), api) == "token-2"
    assert api.posts == 2
    assert len(api.tokens) == 1


def test_a_rejected_create_is_not_retried(monkeypatch):
    from urllib.error import HTTPError

    api = FakeInfluxAuthorizations(["http-400"])

    with pytest.raises(HTTPError):
        create_token(token_provisioner(monkeypatch), api)
    assert api.posts == 1


def test_the_token_create_is_never_retried_inside_one_request_call():
    provisioner = inline_lambda("UpdateSecretLambda")
    create_call = provisioner.split('f"{endpoint}/api/v2/authorizations",', 1)[1].split(")", 1)[0]
    assert "attempts=1" in create_call


def test_bastion_starts_in_parallel_without_package_downloads():
    bastion = (
        template_text()
        .split("  NewBastionHost:", 1)[1]
        .split("  # Managed Policy for Lambda VPC access", 1)[0]
    )

    assert "      - PublicRoute" in bastion
    assert "      - PublicSubnetRouteTableAssociation" in bastion
    assert "DependsOn: InfluxDBInstance" not in bastion
    assert "systemctl enable --now amazon-ssm-agent" in bastion
    assert "yum " not in bastion
    assert "curl " not in bastion
    assert "tar " not in bastion
