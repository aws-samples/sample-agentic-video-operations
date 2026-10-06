"""Translate botocore errors into ToolFailure (tool-contract §2)."""

from botocore.exceptions import (
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    NoCredentialsError,
    ReadTimeoutError,
)

from media_ops_contracts.tool_failure import FailureKind, ToolFailure

_KIND_BY_ERROR_CODE = {
    "ThrottlingException": FailureKind.EXTERNAL_SERVICE_UNAVAILABLE,
    "TooManyRequestsException": FailureKind.EXTERNAL_SERVICE_UNAVAILABLE,
    "ServiceUnavailableException": FailureKind.EXTERNAL_SERVICE_UNAVAILABLE,
    "InternalServerErrorException": FailureKind.EXTERNAL_SERVICE_UNAVAILABLE,
    "NotFoundException": FailureKind.RESOURCE_NOT_FOUND,
    "ResourceNotFoundException": FailureKind.RESOURCE_NOT_FOUND,
    "AccessDeniedException": FailureKind.PERMISSION_DENIED,
    "ForbiddenException": FailureKind.PERMISSION_DENIED,
    "UnauthorizedException": FailureKind.PERMISSION_DENIED,
    "UnrecognizedClientException": FailureKind.PERMISSION_DENIED,
    "ExpiredTokenException": FailureKind.PERMISSION_DENIED,
    "BadRequestException": FailureKind.INVALID_REQUEST,
    "ValidationException": FailureKind.INVALID_REQUEST,
    "ConflictException": FailureKind.INVALID_REQUEST,
    "UnprocessableEntityException": FailureKind.INVALID_REQUEST,
}

_NEXT_ACTION_BY_KIND = {
    FailureKind.EXTERNAL_SERVICE_UNAVAILABLE: "Retry in a minute; the AWS service is busy.",
    FailureKind.RESOURCE_NOT_FOUND: "Check the resource id and region with a list tool.",
    FailureKind.PERMISSION_DENIED: "Check the credentials and the IAM role (`just doctor`).",
    FailureKind.INVALID_REQUEST: "Check the request parameters and the resource's current state.",
    FailureKind.UNEXPECTED_FAILURE: "Check the logs for the request id and report the issue.",
}


def classify_aws_error(error: Exception, *, operation: str) -> ToolFailure:
    """Return the ToolFailure for an AWS SDK error raised by `operation`."""
    kind = _classify_kind(error)
    return ToolFailure(kind, f"{operation} failed: {kind.value}", _NEXT_ACTION_BY_KIND[kind])


def _classify_kind(error: Exception) -> FailureKind:
    if isinstance(error, ClientError):
        code = error.response.get("Error", {}).get("Code", "")
        return _KIND_BY_ERROR_CODE.get(code, FailureKind.UNEXPECTED_FAILURE)
    if isinstance(error, EndpointConnectionError | ConnectTimeoutError | ReadTimeoutError):
        return FailureKind.EXTERNAL_SERVICE_UNAVAILABLE
    if isinstance(error, NoCredentialsError):
        return FailureKind.PERMISSION_DENIED
    return FailureKind.UNEXPECTED_FAILURE
