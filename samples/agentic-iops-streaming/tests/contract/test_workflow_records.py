"""The workflow records, ARN reading, graph building and diff (§8.2, §8.3 step 3).

The hash is the contract between a shown proposal and a stored version, so these pin that it
covers the graph, ignores the time and name, and doesn't move when the API reorders a map.
"""

from datetime import UTC, datetime

import pytest

from agentic_iops_streaming.domain.build_workflow_graph import build_workflow_graph
from agentic_iops_streaming.domain.diff_workflows import diff_workflows
from agentic_iops_streaming.domain.read_arn_parts import read_arn_parts
from agentic_iops_streaming.domain.workflow_records import (
    MAX_WORKFLOW_ID_LENGTH,
    Workflow,
    WorkflowEdge,
    WorkflowProposal,
    build_workflow_id,
    compute_content_sha256,
    describe_version,
    sort_edges,
)

FLOW = "arn:aws:mediaconnect:us-west-2:111122223333:flow:demo-contribution:flow-1"
CHANNEL = "arn:aws:medialive:us-west-2:111122223333:channel:1234567"
ENDPOINT = "arn:aws:mediapackage:us-west-2:111122223333:origin_endpoints/demo-origin-endpoint"
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)

CHAIN = {
    FLOW: {"Name": "demo-contribution", "Sources": [], "Destinations": [{"Arn": CHANNEL}]},
    CHANNEL: {
        "Name": "demo-downstream-channel",
        "Sources": [{"Arn": FLOW}],
        "Destinations": [{"Arn": ENDPOINT}],
    },
    ENDPOINT: {"Name": "demo-origin-endpoint", "Sources": [{"Arn": CHANNEL}], "Destinations": []},
}


@pytest.mark.parametrize(
    ("arn", "service", "resource_type"),
    [
        (FLOW, "mediaconnect", "flow"),
        (CHANNEL, "medialive", "channel"),
        ("arn:aws:medialive:us-west-2:111122223333:input:987654", "medialive", "input"),
        (ENDPOINT, "mediapackage", "origin_endpoints"),
        (
            "arn:aws:mediapackage:us-west-2:111122223333:channels/demo-channel",
            "mediapackage",
            "channels",
        ),
        (
            "arn:aws:mediapackagev2:us-west-2:111122223333:channelGroup/g/channel/c",
            "mediapackagev2",
            "channel",
        ),
        (
            "arn:aws:mediapackagev2:us-west-2:111122223333:channelGroup/g/channel/c/originEndpoint/e",
            "mediapackagev2",
            "originEndpoint",
        ),
        (
            "arn:aws:mediatailor:us-west-2:111122223333:playbackConfiguration/demo",
            "mediatailor",
            "playbackConfiguration",
        ),
        ("arn:aws:cloudfront::111122223333:distribution/E123DEMO456", "cloudfront", "distribution"),
        ("arn:aws:s3:::demo-bucket", "s3", "bucket"),
        ("arn:aws:s3:::demo-bucket/path/to/object.ts", "s3", "object"),
        ("arn:aws:newservice:us-west-2:111122223333:thing:abc", "newservice", "thing"),
        ("not-an-arn", "unknown", "unknown"),
        ("arn:aws:medialive:us-west-2:111122223333", "unknown", "unknown"),
    ],
)
def test_the_service_and_resource_type_are_read_per_service(arn, service, resource_type):
    parts = read_arn_parts(arn)
    assert (parts.service, parts.resource_type) == (service, resource_type)


def test_the_graph_has_one_node_per_resource_and_one_edge_per_link():
    graph = build_workflow_graph(CHAIN)

    assert [node.arn for node in graph.nodes] == sorted([FLOW, CHANNEL, ENDPOINT])
    assert [(edge.source, edge.destination) for edge in graph.edges] == sorted(
        [(FLOW, CHANNEL), (CHANNEL, ENDPOINT)]
    )
    assert all(not edge.inferred for edge in graph.edges)
    assert graph.failed_nodes == []


def test_failed_resources_are_nodes_too_and_stay_separate():
    graph = build_workflow_graph(CHAIN, {CHANNEL: {"Name": "unreadable"}})

    assert [node.arn for node in graph.failed_nodes] == [CHANNEL]
    assert len(graph.nodes) == 3


def test_the_hash_ignores_the_order_the_api_returned_and_the_name_and_time():
    graph = build_workflow_graph(CHAIN)
    reordered = build_workflow_graph({key: CHAIN[key] for key in reversed(list(CHAIN))})

    def hash_of(built):
        return compute_content_sha256(
            entry_point_arn=FLOW,
            nodes=built.nodes,
            failed_nodes=built.failed_nodes,
            edges=built.edges,
        )

    assert hash_of(graph) == hash_of(reordered)
    assert hash_of(graph) != compute_content_sha256(
        entry_point_arn=CHANNEL, nodes=graph.nodes, failed_nodes=[], edges=graph.edges
    )


def test_a_changed_chain_changes_the_hash():
    graph = build_workflow_graph(CHAIN)
    without_endpoint = build_workflow_graph({FLOW: CHAIN[FLOW], CHANNEL: CHAIN[CHANNEL]})
    assert compute_content_sha256(
        entry_point_arn=FLOW, nodes=graph.nodes, failed_nodes=[], edges=graph.edges
    ) != compute_content_sha256(
        entry_point_arn=FLOW,
        nodes=without_endpoint.nodes,
        failed_nodes=[],
        edges=without_endpoint.edges,
    )


def test_edges_are_sorted_and_deduplicated_including_the_inferred_flag():
    edges = sort_edges(
        [
            WorkflowEdge(source=CHANNEL, destination=ENDPOINT),
            WorkflowEdge(source=FLOW, destination=CHANNEL),
            WorkflowEdge(source=FLOW, destination=CHANNEL),
            WorkflowEdge(source=FLOW, destination=CHANNEL, inferred=True),
        ]
    )
    assert [(edge.source, edge.destination, edge.inferred) for edge in edges] == [
        (FLOW, CHANNEL, False),
        (FLOW, CHANNEL, True),
        (CHANNEL, ENDPOINT, False),
    ]


def proposal(graph, version=1) -> WorkflowProposal:
    return WorkflowProposal(
        workflow_id="demo-chain-ab12cd",
        version=version,
        name="demo chain",
        entry_point_arn=FLOW,
        discovered_at=NOW,
        nodes=graph.nodes,
        failed_nodes=graph.failed_nodes,
        edges=graph.edges,
        content_sha256=compute_content_sha256(
            entry_point_arn=FLOW,
            nodes=graph.nodes,
            failed_nodes=graph.failed_nodes,
            edges=graph.edges,
        ),
    )


def test_a_stored_workflow_keeps_the_proposal_graph_and_records_who_confirmed_it():
    stored = Workflow.from_proposal(
        proposal(build_workflow_graph(CHAIN)), confirmed_by="operator-1", confirmed_at=NOW
    )

    assert (stored.confirmed_by, stored.version, stored.entry_point_arn) == ("operator-1", 1, FLOW)
    assert stored.node_arns == sorted([FLOW, CHANNEL, ENDPOINT])
    assert not hasattr(stored, "diff")


def test_the_diff_names_the_nodes_and_edges_that_moved():
    stored = Workflow.from_proposal(
        proposal(build_workflow_graph(CHAIN)), confirmed_by="operator-1", confirmed_at=NOW
    )
    shortened = build_workflow_graph(
        {FLOW: {"Name": "demo-contribution", "Destinations": [{"Arn": CHANNEL}]}, CHANNEL: {}}
    )

    difference = diff_workflows(stored, shortened)

    assert difference.against_version == 1
    assert difference.removed_nodes == [ENDPOINT]
    assert difference.added_nodes == []
    assert [(edge.source, edge.destination) for edge in difference.removed_edges] == [
        (CHANNEL, ENDPOINT)
    ]
    assert not difference.is_empty


def test_an_unchanged_chain_has_an_empty_diff():
    graph = build_workflow_graph(CHAIN)
    stored = Workflow.from_proposal(proposal(graph), confirmed_by="op", confirmed_at=NOW)
    assert diff_workflows(stored, build_workflow_graph(CHAIN)).is_empty


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("demo chain", "demo-chain-ab12cd"),
        ("Demo Chain!!", "demo-chain-ab12cd"),
        ("   ", "workflow-ab12cd"),
        ("a" * 200, "a" * 57 + "-ab12cd"),
    ],
)
def test_the_workflow_id_is_a_bounded_slug_of_the_name(name, expected):
    built = build_workflow_id(name, "ab12cd")
    assert built == expected and len(built) <= MAX_WORKFLOW_ID_LENGTH


def test_a_version_is_described_by_its_number_and_a_short_hash():
    assert describe_version(2, "a" * 64) == f"v2 {'a' * 12}"
