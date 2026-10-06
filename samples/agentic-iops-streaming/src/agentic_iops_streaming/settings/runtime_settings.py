"""Validated agentic-iops-streaming settings (build_a_sample.md §5). Read once at startup."""

from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgenticIopsSettings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    aws_region: str = Field(default="us-west-2")
    agent_model_id: str | None = Field(default=None)
    media_domains: str = Field(default="medialive,mediaconnect")
    allow_writes: bool = Field(default=False)
    memory_id: str = Field(default="")
    approval_signing_key: str = Field(default="")
    agentic_iops_tool_budget: int = Field(default=12, ge=1)
    session_dir: Path = Field(default=Path(".cache/agentic-iops-sessions"))
    # Only `just run agentic-iops-streaming` sets this. It lets a request without an actor header
    # or session id
    # run as one local operator; everywhere else such a request is refused.
    agentic_iops_local_mode: bool = Field(default=False)
    # Set only by the CDK on a runtime with inbound JWT authorization
    # (AGENTIC_IOPS_JWT_DISCOVERY_URL
    # at deploy). The actor is then the verified token's `sub`; the actor header is ignored.
    agentic_iops_jwt_issuer: str = Field(default="")
    agentic_iops_jwt_allowed_clients: str = Field(default="")

    @property
    def jwt_allowed_clients(self) -> frozenset[str]:
        return frozenset(
            c.strip() for c in self.agentic_iops_jwt_allowed_clients.split(",") if c.strip()
        )

    @model_validator(mode="after")
    def require_a_complete_jwt_setting_outside_local_mode(self) -> "AgenticIopsSettings":
        """The runtime reads token claims without re-verifying the signature (AgentCore did), so
        JWT mode must never run where AgentCore is not in front: not in local mode."""
        if self.agentic_iops_jwt_issuer and not self.jwt_allowed_clients:
            raise ValueError(
                "AGENTIC_IOPS_JWT_ISSUER is set, so AGENTIC_IOPS_JWT_ALLOWED_CLIENTS must be too."
            )
        if self.agentic_iops_jwt_issuer and self.agentic_iops_local_mode:
            raise ValueError(
                "AGENTIC_IOPS_JWT_ISSUER is for the deployed runtime; unset "
                "AGENTIC_IOPS_LOCAL_MODE."
            )
        return self

    @model_validator(mode="after")
    def keep_session_files_out_of_the_repository(self) -> "AgenticIopsSettings":
        """Session files hold conversations and pending approvals. Inside the working
        directory (the repository) they must sit under the ignored `.cache/`, which git, the
        image build contexts and `just clean` all cover. A path outside it is the operator's
        own location to protect."""
        here = Path.cwd().resolve()
        target = (here / self.session_dir).resolve()
        if target.is_relative_to(here) and not target.is_relative_to(here / ".cache"):
            raise ValueError(
                f"SESSION_DIR={self.session_dir} is inside {here} but not under .cache/, so "
                "session files could be committed or copied into an image. Use a path under "
                ".cache/ (default .cache/agentic-iops-sessions) or one outside the repository."
            )
        return self

    @model_validator(mode="after")
    def require_a_shared_key_with_shared_sessions(self) -> "AgenticIopsSettings":
        """With AgentCore Memory, a run may resume in another container: approvals signed
        before the pause must verify there too, so the key cannot be per process."""
        if self.memory_id and not self.approval_signing_key:
            raise ValueError("MEMORY_ID is set, so APPROVAL_SIGNING_KEY must be set as well.")
        return self


def load_agentic_iops_settings() -> AgenticIopsSettings:
    return AgenticIopsSettings()
