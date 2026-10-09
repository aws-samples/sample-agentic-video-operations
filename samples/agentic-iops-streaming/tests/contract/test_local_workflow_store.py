"""The local workflow store keeps every read and write inside its root.

`get_workflow` takes a model-supplied `workflow_id`, so the id is held to the generated slug
format and every path is resolved and checked against the resolved root: `../`, a symlinked
folder and a symlinked file all stay out. A file whose record names another key is not that
workflow.
"""

import json

import pytest
from test_dynamodb_workflow_store import workflow

from agentic_iops_streaming.adapters.workflow_store.local_workflow_store import LocalWorkflowStore
from agentic_iops_streaming.workflows.read_workflows import get_workflow, list_workflows
from media_ops_contracts.tool_failure import FailureKind, ToolFailure


@pytest.fixture
def root(tmp_path):
    return tmp_path / "store"


def plant(path, record) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.model_dump_json())


@pytest.mark.parametrize(
    "workflow_id",
    ["../outside", "..", "a/b", "/etc", "Demo-Chain", "demo_chain", "", "x" * 65, "-demo"],
)
def test_an_id_that_is_not_a_generated_slug_is_refused(root, tmp_path, workflow_id):
    plant(tmp_path / "outside" / "v1.json", workflow(workflow_id="outside"))

    with pytest.raises(ToolFailure) as failure:
        get_workflow(LocalWorkflowStore(root), workflow_id, 1)

    assert failure.value.kind is FailureKind.INVALID_REQUEST


def test_a_symlinked_workflow_folder_outside_the_root_is_refused(root, tmp_path):
    plant(tmp_path / "elsewhere" / "v1.json", workflow())
    root.mkdir()
    (root / "demo-chain-ab12cd").symlink_to(tmp_path / "elsewhere", target_is_directory=True)

    with pytest.raises(ToolFailure) as failure:
        get_workflow(LocalWorkflowStore(root), "demo-chain-ab12cd", 1)

    assert failure.value.kind is FailureKind.INVALID_REQUEST
    assert "outside the workflow store" in failure.value.message


def test_a_symlinked_version_file_outside_the_root_is_refused(root, tmp_path):
    plant(tmp_path / "elsewhere.json", workflow())
    (root / "demo-chain-ab12cd").mkdir(parents=True)
    (root / "demo-chain-ab12cd" / "v1.json").symlink_to(tmp_path / "elsewhere.json")

    with pytest.raises(ToolFailure) as failure:
        get_workflow(LocalWorkflowStore(root), "demo-chain-ab12cd", 1)

    assert "outside the workflow store" in failure.value.message


@pytest.mark.parametrize("stored", [{"workflow_id": "another-chain-zz99"}, {"version": 2}])
def test_a_file_whose_record_names_another_key_is_not_that_workflow(root, stored):
    plant(root / "demo-chain-ab12cd" / "v1.json", workflow().model_copy(update=stored))

    with pytest.raises(ToolFailure) as failure:
        get_workflow(LocalWorkflowStore(root), "demo-chain-ab12cd", 1)

    assert failure.value.kind is FailureKind.RESOURCE_NOT_FOUND


def test_listing_skips_folders_that_are_not_workflows(root, tmp_path):
    plant(root / "demo-chain-ab12cd" / "v1.json", workflow())
    plant(tmp_path / "elsewhere" / "v1.json", workflow(workflow_id="elsewhere"))
    (root / "linked-chain-ab12cd").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    (root / "Not A Slug").mkdir()
    (root / "notes.txt").write_text(json.dumps({"x": 1}))

    assert [s.workflow_id for s in list_workflows(LocalWorkflowStore(root))] == [
        "demo-chain-ab12cd"
    ]


def test_a_save_under_an_invalid_id_writes_nothing(root):
    with pytest.raises(ToolFailure):
        LocalWorkflowStore(root).save(workflow(workflow_id="../escape"))

    assert not root.parent.joinpath("escape").exists()


def test_an_empty_read_back_is_reported_as_nothing_read(root, monkeypatch):
    store = LocalWorkflowStore(root)
    monkeypatch.setattr(store, "load", lambda *_: None)

    assert store.save(workflow()) is None
