"""Classified tool failures (tool-contract §2)."""

from enum import StrEnum


class FailureKind(StrEnum):
    INVALID_REQUEST = "InvalidRequest"
    RESOURCE_NOT_FOUND = "ResourceNotFound"
    PERMISSION_DENIED = "PermissionDenied"
    APPROVAL_REQUIRED = "ApprovalRequired"
    APPROVAL_EXPIRED = "ApprovalExpired"
    EXTERNAL_SERVICE_UNAVAILABLE = "ExternalServiceUnavailable"
    UNEXPECTED_FAILURE = "UnexpectedFailure"


class ToolFailure(Exception):
    """A failure a tool can report to the user without leaking internals."""

    def __init__(self, kind: FailureKind, message: str, next_action: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.next_action = next_action
