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
# Resource types whose response bodies are key material: never stored at all.
SECRET_BODY_RESOURCE_TYPES = frozenset({"key"})


class EvidenceStore(BaseModel):
    exchanges: dict[str, HttpExchange] = Field(default_factory=dict)
    tool_runs: list[ToolRun] = Field(default_factory=list)

    def record_exchange(self, exchange: HttpExchange, resource_type: str | None = None) -> str:
        """Store the sanitized form only; findings reference the stable id.

        Sanitization is unconditional: redacted URLs, allowlisted headers and
        a hashed 1 KiB body preview. Key exchanges keep no body at all, only
        the hash and length. Callers keep the raw exchange for parsing.
        """
        evidence_id = f"e{len(self.exchanges) + 1}"
        self.exchanges[evidence_id] = exchange.sanitized(
            EVIDENCE_BODY_PREVIEW_BYTES,
            drop_body=resource_type in SECRET_BODY_RESOURCE_TYPES,
        )
        return evidence_id

    def record_tool_run(self, tool: str, target: str, summary: str) -> str:
        run_id = f"t{len(self.tool_runs) + 1}"
        self.tool_runs.append(
            ToolRun(run_id=run_id, tool=tool, target=redact_url(target), summary=summary)
        )
        return run_id

    def exchanges_for_url(self, url: str) -> list[tuple[str, HttpExchange]]:
        redacted = redact_url(url)
        return [
            (evidence_id, exchange)
            for evidence_id, exchange in self.exchanges.items()
            if exchange.requested_url == redacted
        ]
