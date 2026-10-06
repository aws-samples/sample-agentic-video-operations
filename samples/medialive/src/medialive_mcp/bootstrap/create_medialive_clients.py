"""Build every AWS client the sample uses, real or fixture replay (write_safe_tools.md §2, §4)."""

from dataclasses import dataclass
from typing import Any

from media_ops_contracts.create_aws_client import create_aws_client
from medialive_mcp.settings.runtime_settings import RuntimeSettings


@dataclass(frozen=True)
class MediaLiveClients:
    medialive: Any
    cloudwatch: Any
    logs: Any
    sts: Any
    bedrock: Any
    region: str = ""  # the Region dimension of region-wide metrics


def create_medialive_clients(settings: RuntimeSettings) -> MediaLiveClients:
    def client(service: str) -> Any:
        return create_aws_client(
            service,
            region=settings.aws_region,
            demo=settings.demo,
            demo_scenario=settings.demo_scenario,
            fixtures_dir=settings.fixtures_dir,
        )

    return MediaLiveClients(
        medialive=client("medialive"),
        cloudwatch=client("cloudwatch"),
        logs=client("logs"),
        sts=client("sts"),
        bedrock=client("bedrock-runtime"),
        region=settings.aws_region,
    )
