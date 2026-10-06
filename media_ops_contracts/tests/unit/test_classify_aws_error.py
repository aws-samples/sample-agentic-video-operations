import pytest
from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError

from media_ops_contracts.classify_aws_error import classify_aws_error
from media_ops_contracts.tool_failure import FailureKind


def client_error(code):
    return ClientError({"Error": {"Code": code, "Message": "raw detail"}}, "DescribeChannel")


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (client_error("ThrottlingException"), FailureKind.EXTERNAL_SERVICE_UNAVAILABLE),
        (client_error("NotFoundException"), FailureKind.RESOURCE_NOT_FOUND),
        (client_error("AccessDeniedException"), FailureKind.PERMISSION_DENIED),
        (client_error("BadRequestException"), FailureKind.INVALID_REQUEST),
        (client_error("SomethingNew"), FailureKind.UNEXPECTED_FAILURE),
        (
            EndpointConnectionError(endpoint_url="https://x"),
            FailureKind.EXTERNAL_SERVICE_UNAVAILABLE,
        ),
        (NoCredentialsError(), FailureKind.PERMISSION_DENIED),
        (ValueError("bug"), FailureKind.UNEXPECTED_FAILURE),
    ],
)
def test_classifies_aws_errors(error, kind):
    failure = classify_aws_error(error, operation="describe_channel")
    assert failure.kind is kind
    assert failure.next_action


def test_does_not_leak_raw_aws_error_messages():
    failure = classify_aws_error(
        client_error("AccessDeniedException"), operation="describe_channel"
    )
    assert "raw detail" not in failure.message
