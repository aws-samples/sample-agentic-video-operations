"""Unit tests for coordinator graph routing logic."""

import pytest
from unittest.mock import patch, MagicMock
from coordinator.nodes.classify import classify_router
from coordinator.nodes.approve import approval_router
from coordinator.nodes.merge import merge_router


class TestClassifyRouter:
    def test_simple_query_takes_fast_path(self):
        state = {"classification": {"is_simple": True}}
        assert classify_router(state) == "fast_path"

    def test_complex_query_needs_planning(self):
        state = {"classification": {"is_simple": False}}
        assert classify_router(state) == "needs_planning"

    def test_missing_classification_defaults_to_planning(self):
        state = {"classification": {}}
        assert classify_router(state) == "needs_planning"


class TestApprovalRouter:
    def test_approved_routes_to_approved(self):
        state = {"approval_status": "approved"}
        assert approval_router(state) == "approved"

    def test_not_required_routes_to_approved(self):
        state = {"approval_status": "not_required"}
        assert approval_router(state) == "approved"

    def test_rejected_routes_to_rejected(self):
        state = {"approval_status": "rejected"}
        assert approval_router(state) == "rejected"


class TestMergeRouter:
    def test_all_complete_when_no_pending(self):
        state = {"todos": [
            {"task_id": "t1", "status": "completed"},
            {"task_id": "t2", "status": "completed"},
        ]}
        assert merge_router(state) == "all_complete"

    def test_pending_when_tasks_remain(self):
        state = {"todos": [
            {"task_id": "t1", "status": "completed"},
            {"task_id": "t2", "status": "pending"},
        ]}
        assert merge_router(state) == "pending"

    def test_empty_todos_is_all_complete(self):
        state = {"todos": []}
        assert merge_router(state) == "all_complete"
