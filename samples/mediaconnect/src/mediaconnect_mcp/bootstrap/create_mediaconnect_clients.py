"""Create the external clients shared by the MCP server and domain pack."""

from dataclasses import dataclass
from typing import Any, cast

from media_ops_contracts.create_aws_client import create_aws_client
from mediaconnect_mcp.settings.runtime_settings import RuntimeSettings


@dataclass(frozen=True)
class MediaConnectClients:
    mediaconnect: Any
    cloudwatch: Any
    bedrock: Any


def create_mediaconnect_clients(settings: RuntimeSettings) -> MediaConnectClients:
    def client(service: str) -> Any:
        return create_aws_client(
            service,
            region=cast(str, settings.aws_region),
            demo=settings.demo,
            demo_scenario=settings.demo_scenario,
            fixtures_dir=settings.fixtures_dir,
        )

    return MediaConnectClients(
        mediaconnect=client("mediaconnect"),
        cloudwatch=client("cloudwatch"),
        bedrock=client("bedrock-runtime"),
    )
