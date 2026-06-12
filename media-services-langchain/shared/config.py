"""Shared configuration loaded from environment variables."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    agent_model_id: str = os.getenv("AGENT_MODEL_ID", "us.anthropic.claude-sonnet-4-6")
    memory_id: str = os.getenv("MEMORY_ID", "")
    region: str = os.getenv("AWS_REGION", "us-west-2")
    eml_runtime_arn: str = os.getenv("EML_RUNTIME_ARN", "")
    emx_runtime_arn: str = os.getenv("EMX_RUNTIME_ARN", "")
    agent_name: str = os.getenv("AGENT_NAME", "unknown")
