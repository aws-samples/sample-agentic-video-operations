"""Append-only store of redacted delivery evidence, referenced by id from findings."""

from pydantic import BaseModel, Field

from hls_doctor.adapters.http.http_exchange import HttpExchange
from hls_doctor.adapters.http.redact_url import redact_url


class ToolRun(BaseModel):
    run_id: str
    tool: str
    target: str
    summary: str


EVIDENCE_BODY_PREVIEW_BYTES = 1024


class EvidenceStore(BaseModel):
    exchanges: dict[str, HttpExchange] = Field(default_factory=dict)
    tool_runs: list[ToolRun] = Field(default_factory=list)
    redact_all_query: bool = False

    def record_exchange(self, exchange: HttpExchange) -> str:
        """Store a redacted, body-trimmed copy; findings reference the stable id.

        The stored copy keeps the first kilobyte of the body plus its sha256,
        so reports stay small while the evidence remains verifiable; callers
        keep the untrimmed exchange for parsing.
        """
        evidence_id = f"e{len(self.exchanges) + 1}"
        redacted = exchange.with_preview(EVIDENCE_BODY_PREVIEW_BYTES).model_copy(
            update={
                "url": redact_url(exchange.url, redact_all_query=self.redact_all_query),
                "requested_url": redact_url(
                    exchange.requested_url, redact_all_query=self.redact_all_query
                ),
            }
        )
        self.exchanges[evidence_id] = redacted
        return evidence_id

    def record_tool_run(self, tool: str, target: str, summary: str) -> str:
        run_id = f"t{len(self.tool_runs) + 1}"
        self.tool_runs.append(
            ToolRun(
                run_id=run_id,
                tool=tool,
                target=redact_url(target, redact_all_query=self.redact_all_query),
                summary=summary,
            )
        )
        return run_id

    def exchanges_for_url(self, url: str) -> list[tuple[str, HttpExchange]]:
        redacted = redact_url(url, redact_all_query=self.redact_all_query)
        return [
            (evidence_id, exchange)
            for evidence_id, exchange in self.exchanges.items()
            if exchange.requested_url == redacted
        ]
