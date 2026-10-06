"""Read validated Hydrolix agent settings once per process."""

import re
from functools import lru_cache

from pydantic import ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Databases that describe the server, its users and its settings, never CDN data.
METADATA_DATABASES = frozenset({"system", "information_schema"})


class RuntimeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
        validate_default=True,
    )

    agent_model_id: str = ""
    # Set by the CDK stack (the HydrolixTable parameter). The only table the model may read.
    hydrolix_table: str = ""
    # Set by the CDK stack on the runtime (agentMemory.attrMemoryId).
    memory_id: str = ""
    # Set by the CDK stack only on a runtime with inbound JWT authorization
    # (HYDROLIX_JWT_DISCOVERY_URL at deploy). The actor is then the verified token's `sub`.
    hydrolix_jwt_issuer: str = ""
    hydrolix_jwt_allowed_clients: str = ""

    @property
    def jwt_allowed_clients(self) -> frozenset[str]:
        clients = self.hydrolix_jwt_allowed_clients.split(",")
        return frozenset(client.strip() for client in clients if client.strip())

    @field_validator("agent_model_id", "memory_id")
    @classmethod
    def require_a_value(cls, value: str, info: ValidationInfo) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError(f"Missing required setting(s): {(info.field_name or '').upper()}")
        return cleaned

    @field_validator("hydrolix_table")
    @classmethod
    def require_a_data_table(cls, value: str) -> str:
        # The same rule as the CDK HydrolixTable AllowedPattern: database.table, neither part
        # starting with "_", and never a metadata database (system, information_schema).
        cleaned = value.strip()
        part = r"[A-Za-z0-9-][A-Za-z0-9_-]*"
        if not re.fullmatch(rf"{part}\.{part}", cleaned):
            raise ValueError(
                "HYDROLIX_TABLE must be database.table: letters, digits, _ or -, "
                "neither part starting with _"
            )
        if cleaned.split(".")[0].lower() in METADATA_DATABASES:
            raise ValueError(
                "HYDROLIX_TABLE must be a data table, not in system or information_schema"
            )
        return cleaned

    @model_validator(mode="after")
    def require_both_jwt_settings_or_neither(self) -> "RuntimeSettings":
        # Both or neither: half a setting must not silently fall back to IAM mode.
        if bool(self.hydrolix_jwt_issuer) != bool(self.jwt_allowed_clients):
            raise ValueError(
                "Set both HYDROLIX_JWT_ISSUER and HYDROLIX_JWT_ALLOWED_CLIENTS, or neither."
            )
        return self


@lru_cache
def load_runtime_settings() -> RuntimeSettings:
    return RuntimeSettings()
