# Fixtures

Recorded-style AWS responses for `DEMO=1` and the offline tests (write_safe_tools.md §4).
`fixtures/<scenario>/<service>.<operation>.json` answers `client.<operation>(...)`.
A `{"sequence": [...]}` file answers successive calls in order, and the last answer repeats.

All identifiers are placeholders: account `111122223333`, channel `1234567`, `demo-*` names.
The responses are synthetic, built in the shape of the real AWS API responses. Replace them
with sanitized recordings when those are available.

| Scenario | Story | Used by |
|---|---|---|
| `input_loss` | MediaLive pipeline 0 stops receiving its SRT input; the channel stays RUNNING and outputs slate | medialive, langchain EML |
