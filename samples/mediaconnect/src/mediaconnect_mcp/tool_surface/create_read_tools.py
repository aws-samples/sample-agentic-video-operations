"""Create the MediaConnect read tools used by both MCP and the domain pack."""

import time
from datetime import UTC, datetime
from functools import partial
from typing import Annotated

from annotated_types import Ge, Le

from media_ops_contracts.domain_pack import ReadTool
from media_ops_video_quality.sampling_limits import (
    MAX_FRAMES,
    MAX_WINDOW_SECONDS,
    MIN_FRAMES,
    MIN_WINDOW_SECONDS,
)
from mediaconnect_mcp.adapters.cloudwatch.read_flow_metrics import (
    FlowMetrics,
    MetricCategory,
    read_flow_metrics,
)
from mediaconnect_mcp.adapters.media_connect.describe_flow import (
    FlowDetails,
)
from mediaconnect_mcp.adapters.media_connect.describe_flow import (
    describe_flow as describe_flow_adapter,
)
from mediaconnect_mcp.adapters.media_connect.describe_flow_source_metadata import (
    FlowSourceMetadata,
)
from mediaconnect_mcp.adapters.media_connect.describe_flow_source_metadata import (
    describe_flow_source_metadata as describe_flow_source_metadata_adapter,
)
from mediaconnect_mcp.adapters.media_connect.list_flows import (
    FlowList,
)
from mediaconnect_mcp.adapters.media_connect.list_flows import (
    list_flows as list_flows_adapter,
)
from mediaconnect_mcp.bootstrap.create_mediaconnect_clients import MediaConnectClients
from mediaconnect_mcp.settings.runtime_settings import RuntimeSettings
from mediaconnect_mcp.workflows.assess_flow_visual_quality import (
    FlowVisualQuality,
    assess_flow_visual_quality,
)
from mediaconnect_mcp.workflows.build_metrics_table import MetricsTable, build_metrics_table
from mediaconnect_mcp.workflows.describe_flow_thumbnail import (
    FlowThumbnailDescription,
)
from mediaconnect_mcp.workflows.describe_flow_thumbnail import (
    describe_flow_thumbnail as describe_flow_thumbnail_workflow,
)
from mediaconnect_mcp.workflows.identify_flow_issues import FlowIssueReport, identify_flow_issues
from mediaconnect_mcp.workflows.inspect_all_flow_metrics import (
    AllFlowMetrics,
    inspect_all_flow_metrics,
)


def create_read_tools(settings: RuntimeSettings, clients: MediaConnectClients) -> list[ReadTool]:
    def read(category: MetricCategory, flow_arn: str, hours_back: int) -> FlowMetrics:
        return read_flow_metrics(
            clients.cloudwatch,
            flow_arn,
            category,
            hours_back,
            datetime.now(UTC),
        )

    def read_all(flow_arn: str, hours_back: int) -> AllFlowMetrics:
        return inspect_all_flow_metrics(
            flow_arn,
            partial(read, flow_arn=flow_arn, hours_back=hours_back),
        )

    def list_flows() -> FlowList:
        """List MediaConnect flows in the configured AWS region."""
        return list_flows_adapter(clients.mediaconnect)

    def describe_flow(flow_arn: str) -> FlowDetails:
        """Describe one flow's state, source, outputs, and AWS errors."""
        return describe_flow_adapter(clients.mediaconnect, flow_arn)

    def describe_flow_source_metadata(flow_arn: str) -> FlowSourceMetadata:
        """Read transport-stream and NDI metadata for one flow source."""
        return describe_flow_source_metadata_adapter(clients.mediaconnect, flow_arn)

    def describe_flow_thumbnail(flow_arn: str) -> FlowThumbnailDescription:
        """Describe the current source thumbnail with the configured vision model."""
        return describe_flow_thumbnail_workflow(
            clients.mediaconnect,
            clients.bedrock,
            flow_arn,
            settings.thumbnail_model_id,
        )

    # Fixture replay carries its own timestamps, so DEMO never waits between samples.
    sleep = (lambda seconds: None) if settings.demo else time.sleep

    def analyze_flow_visual_quality(
        flow_arn: str,
        frames: Annotated[int | None, Ge(MIN_FRAMES), Le(MAX_FRAMES)] = None,
        window_seconds: Annotated[
            int | None, Ge(MIN_WINDOW_SECONDS), Le(MAX_WINDOW_SECONDS)
        ] = None,
    ) -> FlowVisualQuality:
        """Sample the flow's source thumbnail over a window and score the picture: freeze,
        black, slate, blur and a blockiness estimate, plus a vision rubric, checked against
        the flow's content-quality and source-connection metrics. Blocks for the whole
        window. Without thumbnails or a vision verdict the flow is UNVERIFIED, never healthy."""
        # None means the default; 0 is out of bounds and refused, never replaced. The bounds
        # are in the MCP schema (Ge/Le) and enforced by the sampler for every caller.
        return assess_flow_visual_quality(
            clients,
            flow_arn,
            frames=settings.visual_quality_frames if frames is None else frames,
            window_seconds=(
                settings.visual_quality_window_seconds if window_seconds is None else window_seconds
            ),
            vision_model_id=settings.thumbnail_model_id,
            sleep=sleep,
        )

    def get_flow_health_metrics(flow_arn: str, hours_back: int = 1) -> FlowMetrics:
        """Read flow-level transport and TR 101 290 metrics."""
        return read(MetricCategory.FLOW_HEALTH, flow_arn, hours_back)

    def get_source_health_metrics(flow_arn: str, hours_back: int = 1) -> FlowMetrics:
        """Read source connection, loss, recovery, and merge metrics."""
        return read(MetricCategory.SOURCE_HEALTH, flow_arn, hours_back)

    def get_output_health_metrics(flow_arn: str, hours_back: int = 1) -> FlowMetrics:
        """Read output connection, packet, and payload metrics."""
        return read(MetricCategory.OUTPUT_HEALTH, flow_arn, hours_back)

    def get_media_health_metrics(flow_arn: str, hours_back: int = 1) -> FlowMetrics:
        """Read source jitter, latency, uptime, and consecutive-drop metrics."""
        return read(MetricCategory.MEDIA_HEALTH, flow_arn, hours_back)

    def get_content_quality_metrics(flow_arn: str, hours_back: int = 1) -> FlowMetrics:
        """Read missing-stream, black-frame, frozen-frame, and silence metrics."""
        return read(MetricCategory.CONTENT_QUALITY, flow_arn, hours_back)

    def get_all_metrics(flow_arn: str, hours_back: int = 1) -> AllFlowMetrics:
        """Read all five MediaConnect metric categories."""
        return read_all(flow_arn, hours_back)

    def check_flow_issues(flow_arn: str, hours_back: int = 24) -> FlowIssueReport:
        """Identify non-zero loss, drop, disconnect, error, and missing-stream signals."""
        return identify_flow_issues(read_all(flow_arn, hours_back))

    def get_metrics_table(flow_arn: str, hours_back: int = 6) -> MetricsTable:
        """Flatten all metric points into chronological rows for charting."""
        return build_metrics_table(read_all(flow_arn, hours_back))

    return [
        list_flows,
        describe_flow,
        describe_flow_source_metadata,
        describe_flow_thumbnail,
        analyze_flow_visual_quality,
        get_flow_health_metrics,
        get_source_health_metrics,
        get_output_health_metrics,
        get_media_health_metrics,
        get_content_quality_metrics,
        get_all_metrics,
        check_flow_issues,
        get_metrics_table,
    ]
