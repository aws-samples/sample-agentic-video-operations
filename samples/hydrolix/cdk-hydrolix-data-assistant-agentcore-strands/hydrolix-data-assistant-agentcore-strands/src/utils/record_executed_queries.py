"""Record each Hydrolix query after it ran, with its status (T41).

A record goes to the request's own list, which the response streams back to its caller,
and to the results table under the verified caller's `sub`. Nothing is written in IAM mode,
where there is no verified caller (memory is off there too). A refused or cancelled call
never ran, so it isn't recorded.
"""

import time
from typing import Any

from strands.hooks import AfterToolCallEvent, HookProvider, HookRegistry

from .query_record import MAX_SQL_CHARS, MAX_TEXT_CHARS, QueryRecord, truncate
from .request_context import get_request_context
from .utils import save_query_record


class RecordExecutedQueries(HookProvider):
    def __init__(self, agent_name: str, question: str) -> None:
        self.agent_name = agent_name
        self.question, self.question_omitted = truncate(question, MAX_TEXT_CHARS)

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(AfterToolCallEvent, self.record)

    def record(self, event: AfterToolCallEvent) -> None:
        if event.tool_use["name"] != "run_select_query" or event.cancel_message:
            return
        tool_input = event.tool_use.get("input") or {}
        if not isinstance(tool_input, dict):
            tool_input = {}
        sql, sql_omitted = truncate(str(tool_input.get("query", "")), MAX_SQL_CHARS)
        purpose, purpose_omitted = truncate(str(tool_input.get("purpose", "")), MAX_TEXT_CHARS)
        omitted = {
            name: count
            for name, count in (
                ("query", sql_omitted),
                ("query_description", purpose_omitted),
                ("user_prompt", self.question_omitted),
            )
            if count
        }
        record = QueryRecord(
            agent_name=self.agent_name,
            question=self.question,
            sql=sql,
            purpose=purpose,
            status=str(event.result.get("status", "error")),
            executed_at_ms=time.time_ns() // 1_000_000,
            omitted=omitted,
        )
        request = get_request_context()
        request.query_records.append(record)  # list.append is atomic: subagents may overlap
        if request.actor_id:
            save_query_record(request.actor_id, request.prompt_uuid, record)
