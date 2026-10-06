"""Hydrolix query records are per verified user, recorded as they ran (T41).

The web app used to read the results table by a client-chosen prompt_uuid with a role every
signed-in user shares, so anyone could read anyone's SQL. Now the runtime streams each
request's own records back to its caller, the browser reads no table, and the table (keyed
by the verified `sub`) is only ever written.
"""

import asyncio
import json
import sys
import types
import uuid
from pathlib import Path

import pytest
from botocore.exceptions import ClientError
from strands import tool
from test_hydrolix_bound_model_sql import (  # noqa: F401 - pytest fixtures
    ALLOWED_SQL,
    ScriptedModel,
    call,
    runtime,
    say,
)
from test_hydrolix_caller_identity import CLIENT, ISSUER, token

WEB_APP = (
    Path(__file__).resolve().parents[2]
    / "samples/hydrolix/amplify-hydrolix-data-assistant-agentcore-strands"
)


class SubagentCallingOrchestrator:
    """Stands in for the orchestrator model: asks hydrolix_agent once, as Strands would (in
    a worker thread), then answers."""

    def __init__(self, *, hooks, **_):
        self.hooks = hooks

    async def stream_async(self, _prompt):
        tools = sys.modules["src.tools"]
        await asyncio.to_thread(tools.hydrolix_agent, "How many requests?")
        yield {"data": "Done."}


class FakeDynamoDB:
    def __init__(self, error: Exception | None = None) -> None:
        self.items: list[dict] = []
        self.error = error

    def put_item(self, TableName: str, Item: dict) -> dict:  # noqa: N803 (boto3's names)
        if self.error:
            raise self.error
        self.items.append(Item)
        return {}


@pytest.fixture
def results(runtime, monkeypatch):  # noqa: F811
    utils = sys.modules["src.utils.utils"]
    recorder = sys.modules["src.utils.record_executed_queries"]
    dynamodb = FakeDynamoDB()
    monkeypatch.setattr(utils, "QUESTION_ANSWERS_TABLE", "results-table")
    monkeypatch.setattr(utils.boto3, "client", lambda service: dynamodb)
    monkeypatch.setattr(recorder, "save_query_record", utils.save_query_record)  # the real one
    monkeypatch.setattr(runtime.app, "Agent", SubagentCallingOrchestrator)
    monkeypatch.setattr(runtime.app, "BedrockModel", lambda **_: object())
    monkeypatch.setattr(runtime.app, "get_agentcore_memory_messages", lambda *_: [])
    identity = sys.modules["src.utils.identify_caller"]

    def ask_as(subject, sql, *, session, jwt=True):
        # Each user on their own microVM, as AgentCore runs separate runtime sessions.
        monkeypatch.setattr(identity, "CONTAINER_OWNER", identity.ContainerOwner())
        if jwt:
            settings = runtime.app.runtime_settings.model_copy(
                update={"hydrolix_jwt_issuer": ISSUER, "hydrolix_jwt_allowed_clients": CLIENT}
            )
            monkeypatch.setattr(runtime.app, "runtime_settings", settings)
        model = ScriptedModel(
            [call("run_select_query", "t1", query=sql, purpose=f"{subject}'s question")],
            [say("42")],
        )
        monkeypatch.setattr(runtime.runner, "BedrockModel", lambda **_: model)
        headers = {"Authorization": token(subject)} if jwt else {}
        context = types.SimpleNamespace(session_id=session, request_headers=headers)
        payload = {"prompt": "hi", "prompt_uuid": f"uuid-{subject}"}

        async def collect():
            return [json.loads(c) async for c in runtime.app.agent_invocation(payload, context)]

        return asyncio.run(collect())

    runtime.dynamodb, runtime.ask_as = dynamodb, ask_as
    return runtime


def streamed_queries(chunks):
    [record] = [chunk for chunk in chunks if "query_results" in chunk]
    return record["query_results"]


ALICE_SQL = "SELECT count() FROM video.cmcd WHERE pop = 'alice-pop'"
BOB_SQL = "SELECT count() FROM video.cmcd WHERE pop = 'bob-pop'"


def test_each_user_gets_only_their_own_queries_and_items_carry_their_sub(results):
    alice = results.ask_as("alice", ALICE_SQL, session="alice-runtime-session-00000000000000")
    bob = results.ask_as("bob", BOB_SQL, session="bob-runtime-session-0000000000000000")

    assert [q["query"] for q in streamed_queries(alice)] == [ALICE_SQL]
    assert [q["query"] for q in streamed_queries(bob)] == [BOB_SQL]
    assert streamed_queries(alice)[0]["status"] == "success"
    written = {(item["actor_id"]["S"], item["sql_query"]["S"]) for item in results.dynamodb.items}
    assert written == {("alice", ALICE_SQL), ("bob", BOB_SQL)}


def test_iam_mode_streams_the_queries_back_but_writes_nothing(results):
    chunks = results.ask_as(
        "anyone", ALICE_SQL, session="iam-runtime-session-0000000000000000", jwt=False
    )

    assert [q["query"] for q in streamed_queries(chunks)] == [ALICE_SQL]
    assert results.dynamodb.items == []


def test_a_query_that_fails_on_the_cluster_is_recorded_with_its_error_status(results):
    @tool
    def run_select_query(query: str, purpose: str, max_cells: int | None = None) -> str:
        """Run one SELECT."""
        raise RuntimeError("cluster rejected the query")

    results.mcp.tools[0] = run_select_query

    chunks = results.ask_as("alice", ALICE_SQL, session="alice-runtime-session-00000000000000")

    [query] = streamed_queries(chunks)
    assert query["status"] == "error"
    assert results.dynamodb.items[0]["status"]["S"] == "error"


def test_a_refused_query_is_neither_streamed_nor_written(results):
    chunks = results.ask_as(
        "alice", "SELECT * FROM other_db.t", session="alice-runtime-session-00000000000000"
    )

    assert streamed_queries(chunks) == [] and results.dynamodb.items == []


def record(sql="SELECT 1 FROM video.cmcd", at_ms=1_759_752_000_123):
    query_record = sys.modules["src.utils.query_record"]
    return query_record.QueryRecord("hydrolix_agent", "q", sql, "p", "success", at_ms)


def test_two_records_in_the_same_millisecond_get_distinct_ordered_sort_keys(results):
    save = sys.modules["src.utils.utils"].save_query_record

    assert save("alice", "uuid-1", record()) and save("alice", "uuid-1", record())
    assert save("alice", "uuid-1", record(at_ms=1_759_752_000_124))

    keys = [item["recorded_at"]["S"] for item in results.dynamodb.items]
    assert len(set(keys)) == 3
    assert keys[0].split("#")[0] == keys[1].split("#")[0] < keys[2].split("#")[0]


def test_an_oversized_query_is_truncated_with_a_marker_and_fits_one_item(results):
    hook_module = sys.modules["src.utils.record_executed_queries"]
    context = results.context.set_request_context("uuid-1", actor_id="alice")
    huge = "SELECT " + "x, " * 200_000 + "1 FROM video.cmcd"  # about 600 KB
    event = types.SimpleNamespace(
        tool_use={"name": "run_select_query", "input": {"query": huge, "purpose": "p"}},
        cancel_message=None,
        result={"status": "success"},
    )

    hook_module.RecordExecutedQueries("hydrolix_agent", "q").record(event)

    [saved] = context.query_records
    assert len(saved.sql) == 16_000 and saved.omitted == {"query": len(huge) - 16_000}
    [item] = results.dynamodb.items
    assert item["truncated"] == {"BOOL": True}
    assert item["omitted_characters"] == {"M": {"query": {"N": str(len(huge) - 16_000)}}}
    assert len(json.dumps(item).encode()) < 400_000


def test_a_failed_write_logs_the_class_only_and_returns(results, capsys):
    error = {"Code": "ValidationException", "Message": "Item too large: SECRET-SQL-TEXT"}
    results.dynamodb.error = ClientError({"Error": error}, "PutItem")

    assert results_save(results) is False

    logged = capsys.readouterr().out
    assert "ClientError" in logged and "SECRET-SQL-TEXT" not in logged


def results_save(results):
    return sys.modules["src.utils.utils"].save_query_record("alice", "uuid-1", record())


def test_the_web_app_reads_no_dynamodb_table():
    sources = [path.read_text() for path in (WEB_APP / "src").rglob("*.js")]
    manifest = json.loads((WEB_APP / "package.json").read_text())

    assert not any("dynamodb" in source.lower() for source in sources)
    assert not any("dynamodb" in name for name in manifest["dependencies"])


# --- GPT review of a28e49e -----------------------------------------------------------


class SubagentThenFailure(SubagentCallingOrchestrator):
    """A query runs, then the orchestrator fails."""

    async def stream_async(self, _prompt):
        tools = sys.modules["src.tools"]
        await asyncio.to_thread(tools.hydrolix_agent, "How many requests?")
        yield {"data": "Partial answer. "}
        raise RuntimeError("model stream broke")


class SubagentThenStall(SubagentCallingOrchestrator):
    """A query runs, then the orchestrator outlives the request deadline."""

    async def stream_async(self, _prompt):
        tools = sys.modules["src.tools"]
        await asyncio.to_thread(tools.hydrolix_agent, "How many requests?")
        yield {"data": "Partial answer. "}
        await asyncio.sleep(5)
        yield {"data": "never"}


@pytest.mark.parametrize("orchestrator", [SubagentThenFailure, SubagentThenStall])
def test_queries_that_ran_are_the_last_record_even_when_the_request_fails(
    results, monkeypatch, orchestrator
):
    monkeypatch.setattr(results.app, "Agent", orchestrator)
    monkeypatch.setattr(results.context, "REQUEST_TIMEOUT_SECONDS", 3)

    chunks = results.ask_as("alice", ALICE_SQL, session="alice-runtime-session-00000000000000")

    assert [q["query"] for q in chunks[-1]["query_results"]] == [ALICE_SQL]
    assert any("error" in chunk for chunk in chunks[:-1])


def test_a_prompt_uuid_that_is_not_a_uuid_is_replaced_so_the_item_fits(results, monkeypatch):
    crafted = "x" * 410_000
    real_ask = results.app.agent_invocation

    async def with_crafted_uuid(payload, context):
        async for chunk in real_ask(payload | {"prompt_uuid": crafted}, context):
            yield chunk

    monkeypatch.setattr(results.app, "agent_invocation", with_crafted_uuid)

    results.ask_as("alice", ALICE_SQL, session="alice-runtime-session-00000000000000")

    [item] = results.dynamodb.items
    assert str(uuid.UUID(item["prompt_uuid"]["S"])) == item["prompt_uuid"]["S"]
    assert len(json.dumps(item).encode()) < 400_000


def test_a_real_uuid_is_kept():
    app = sys.modules.get("app")
    given = "0b9a0c2e-6a7b-4f2e-9d7e-3c1a2b4d5e6f"
    assert app.bounded_prompt_uuid(given) == given
    assert app.bounded_prompt_uuid(given.upper()) == given  # canonical form
    for bad in ("", "not-a-uuid", "x" * 410_000, 123, None):
        assert app.bounded_prompt_uuid(bad) != bad and uuid.UUID(app.bounded_prompt_uuid(bad))


def test_sql_that_looks_like_a_truncation_marker_is_not_marked_truncated(results):
    hook_module = sys.modules["src.utils.record_executed_queries"]
    context = results.context.set_request_context("uuid-1", actor_id="alice")
    literal = "SELECT 1 FROM video.cmcd -- …[truncated 99 characters]"
    event = types.SimpleNamespace(
        tool_use={"name": "run_select_query", "input": {"query": literal, "purpose": "p"}},
        cancel_message=None,
        result={"status": "success"},
    )

    hook_module.RecordExecutedQueries("hydrolix_agent", "q").record(event)

    [saved] = context.query_records
    assert saved.sql == literal and saved.omitted == {}
    assert saved.as_stream_item()["truncated"] is False
    [item] = results.dynamodb.items
    assert item["truncated"] == {"BOOL": False}
