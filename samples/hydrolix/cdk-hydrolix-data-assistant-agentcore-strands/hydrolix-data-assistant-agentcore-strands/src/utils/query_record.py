"""One Hydrolix query as it ran: what the response shows its caller and the table keeps."""

from dataclasses import dataclass, field

# DynamoDB items are capped at 400 KB. These caps keep a record far under it whatever the
# model wrote. A cut is recorded as metadata (truncated, omitted_characters), never as a
# marker in the text, which a query could contain literally.
MAX_SQL_CHARS = 16_000
MAX_TEXT_CHARS = 4_000


def truncate(text: str, limit: int) -> tuple[str, int]:
    """The text cut to `limit` characters, and how many were omitted (0 if none)."""
    return text[:limit], max(0, len(text) - limit)


@dataclass(frozen=True)
class QueryRecord:
    agent_name: str
    question: str  # the subagent's question, as the orchestrator wrote it
    sql: str
    purpose: str
    status: str  # the tool result's: "success" or "error"
    executed_at_ms: int
    omitted: dict[str, int] = field(default_factory=dict)  # stream field -> characters cut

    def as_stream_item(self) -> dict[str, object]:
        """The shape the web app's query panel and chart prompt read."""
        return {
            "query": self.sql,
            "query_description": self.purpose,
            "agent_name": self.agent_name,
            "user_prompt": self.question,
            "status": self.status,
            "truncated": bool(self.omitted),
            "omitted_characters": dict(self.omitted),
            "query_results": [],  # rows stay in the agent's answer; the record has the SQL
        }
