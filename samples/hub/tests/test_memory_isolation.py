"""Tests for memory namespace isolation."""

from shared.memory import build_config


class TestMemoryNamespacing:
    def test_coordinator_namespace(self):
        config = build_config("coordinator", "user-123", "session-abc")
        assert config["configurable"]["actor_id"] == "coordinator-user-123"
        assert config["configurable"]["thread_id"] == "session-abc"

    def test_eml_namespace(self):
        config = build_config("eml", "task-456", "task-task-456")
        assert config["configurable"]["actor_id"] == "eml-task-456"
        assert config["configurable"]["thread_id"] == "task-task-456"

    def test_emx_namespace(self):
        config = build_config("emx", "task-789", "task-task-789")
        assert config["configurable"]["actor_id"] == "emx-task-789"

    def test_namespaces_dont_collide(self):
        coord = build_config("coordinator", "same-id", "same-session")
        eml = build_config("eml", "same-id", "same-session")
        emx = build_config("emx", "same-id", "same-session")

        actor_ids = {
            coord["configurable"]["actor_id"],
            eml["configurable"]["actor_id"],
            emx["configurable"]["actor_id"],
        }
        assert len(actor_ids) == 3
