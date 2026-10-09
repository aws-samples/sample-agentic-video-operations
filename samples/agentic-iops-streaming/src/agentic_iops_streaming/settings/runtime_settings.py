"""Validated agentic-iops-streaming settings (build_a_sample.md §5). Read once at startup."""

import os
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from agentic_iops_streaming.settings.refuse_renamed_settings import refuse_renamed_settings


class AgenticIopsSettings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    aws_region: str = Field(default="us-west-2")
    agent_model_id: str | None = Field(default=None)
    media_domains: str = Field(default="medialive,mediaconnect")
    allow_writes: bool = Field(default=False)
    memory_id: str = Field(default="")
    approval_signing_key: str = Field(default="")
    agentic_iops_tool_budget: int = Field(default=12, ge=1)
    agentic_iops_port: int = Field(default=8080, ge=1, le=65535)
    session_dir: Path = Field(default=Path(".cache/agentic-iops-sessions"))
    # DEMO replay for the coordinator's own tools (the packs read these too): the workflow
    # tools answer from `fixtures/<DEMO_SCENARIO>` instead of AWS.
    demo: bool = Field(default=False)
    demo_scenario: str = Field(default="")
    fixtures_dir: Path = Field(default=Path("fixtures"))
    # The workflow tools (extend_agentic_iops_streaming.md §8). They read and write only this
    # sample's own store, and discovery leaves nothing in the account, so they are on by
    # default and gated separately from ALLOW_WRITES.
    allow_workflow_discovery: bool = Field(default=True)
    # Set by the CDK: the workflow store's table. Empty means the local store under .cache/.
    workflow_table_name: str = Field(default="")
    workflow_dir: Path = Field(default=Path(".cache/workflows"))
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
    def serve_the_container_on_agentcores_port(self) -> "AgenticIopsSettings":
        """AGENTIC_IOPS_PORT is for local runs. In the deployed image (DOCKER_CONTAINER=1),
        AgentCore reaches the container on 8080, so another port would only fail health
        checks without saying why."""
        if os.environ.get("DOCKER_CONTAINER") == "1" and self.agentic_iops_port != 8080:
            raise ValueError(
                f"AGENTIC_IOPS_PORT={self.agentic_iops_port} in the container: AgentCore serves "
                "the container on 8080, and the setting is for local runs. Unset it."
            )
        return self

    @model_validator(mode="after")
    def refuse_old_setting_names(self) -> "AgenticIopsSettings":
        """A setting under its old name is ignored, which fails open."""
        refuse_renamed_settings(os.environ)
        return self

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
    def keep_local_state_out_of_the_repository(self) -> "AgenticIopsSettings":
        """Session files hold conversations and pending approvals; stored workflows map the
        account's live chain. Inside the working directory (the repository) both must sit
        under the ignored `.cache/`, which git, the image build contexts and `just clean` all
        cover. A path outside it is the operator's own location to protect."""
        require_under_cache("SESSION_DIR", self.session_dir, "session files")
        require_under_cache("WORKFLOW_DIR", self.workflow_dir, "stored workflows")
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


def require_under_cache(setting: str, path: Path, holds: str) -> None:
    here = Path.cwd().resolve()
    target = (here / path).resolve()
    if target.is_relative_to(here) and not target.is_relative_to(here / ".cache"):
        raise ValueError(
            f"{setting}={path} is inside {here} but not under .cache/, so {holds} could be "
            "committed or copied into an image. Use a path under .cache/ or one outside the "
            "repository."
        )
