"""Typed view of Apple mediastreamvalidator output: an independent cross-check."""

from typing import Protocol

from pydantic import BaseModel, Field


class ValidatorIssue(BaseModel):
    severity: str = "warning"
    message: str
    url: str | None = None


class ValidatorReport(BaseModel):
    url: str
    available: bool
    unavailable_reason: str | None = None
    issues: list[ValidatorIssue] = Field(default_factory=list)


class ValidateStream(Protocol):
    """The conformance-validator port; Apple's tool and fixture replay implement it."""

    def __call__(self, url: str) -> ValidatorReport: ...


def parse_validator_output(url: str, payload: dict) -> ValidatorReport:
    """Normalize the validator JSON: every entry in `messages` becomes an issue."""
    issues = [
        ValidatorIssue(
            severity=str(entry.get("errorStatusCode", entry.get("severity", "warning"))),
            message=str(entry.get("errorComment", entry.get("message", entry))),
            url=entry.get("url"),
        )
        for entry in payload.get("messages", payload.get("issues", []))
    ]
    return ValidatorReport(url=url, available=True, issues=issues)
