import re
from pathlib import Path
from textwrap import dedent

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


def test_named_stream_log_config_and_processor_are_stack_prefixed():
    template = template_text()

    assert "Name: !Sub '${AWS::StackName}-${KinesisStreamName}'" in template
    assert "Name: !Sub '${AWS::StackName}-cmcd-realtime-logs'" in template
    assert "FunctionName: !Sub '${AWS::StackName}-cmcd-kinesis-processor'" in template
    assert "FunctionName: !Sub '${AWS::StackName}-deploy-index-html'" in template


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


def test_token_custom_resource_keeps_an_s3_response_path_until_delete_finishes():
    template = template_text()
    endpoint = template.split("  S3GatewayEndpoint:", 1)[1].split("  PrivateRoute:", 1)[0]
    custom_resource = template.split("  UpdateSecretCustomResource:", 1)[1].split(
        "  # IAM Role for Secret Rotation", 1
    )[0]

    assert "Type: AWS::EC2::VPCEndpoint" in endpoint
    assert "VpcEndpointType: Gateway" in endpoint
    assert "ServiceName: !Sub 'com.amazonaws.${AWS::Region}.s3'" in endpoint
    assert "RouteTableIds:\n        - !Ref PrivateRouteTable" in endpoint
    for dependency in (
        "PrivateRoute",
        "PrivateSubnet1RouteTableAssociation",
        "PrivateSubnet2RouteTableAssociation",
        "S3GatewayEndpoint",
    ):
        assert f"      - {dependency}" in custom_resource


def test_s3_gateway_endpoint_allows_only_response_and_stack_bucket_access():
    endpoint = template_text().split("  S3GatewayEndpoint:", 1)[1].split("  PrivateRoute:", 1)[0]

    assert "PolicyDocument:" in endpoint
    assert "cloudformation-custom-resource-response-${RegionWithoutDashes}/*" in endpoint
    assert "Fn::Split:" in endpoint
    assert "- !Ref AWS::Region" in endpoint
    assert "- !GetAtt ContentBucket.Arn" in endpoint
    assert "arn:${AWS::Partition}:s3:::${DeploymentArtifactsBucketName}" in endpoint
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
    assert endpoint.count("DeploymentArtifactsBucketName") == 2
    assert "Action: '*'" not in endpoint
    assert "Resource: '*'" not in endpoint


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
