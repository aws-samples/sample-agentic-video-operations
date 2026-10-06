"""Build every AWS client the sample uses, real or fixture replay (tool-contract §2, §4)."""

from dataclasses import dataclass
from typing import Any

from media_ops_contracts.create_aws_client import create_aws_client
from medialive_mcp.settings.runtime_settings import RuntimeSettings


@dataclass(frozen=True)
class MediaLiveClients:
    medialive: Any
    cloudwatch: Any
    logs: Any
    bedrock: Any


def create_medialive_clients(settings: RuntimeSettings) -> MediaLiveClients:
    def client(service: str) -> Any:
        return create_aws_client(
            service,
            region=settings.aws_region,
            demo_scenario=settings.replay_scenario,
            fixtures_dir=settings.fixtures_dir,
        )

    return MediaLiveClients(
        medialive=client("medialive"),
        cloudwatch=client("cloudwatch"),
        logs=client("logs"),
        bedrock=client("bedrock-runtime"),
    )
