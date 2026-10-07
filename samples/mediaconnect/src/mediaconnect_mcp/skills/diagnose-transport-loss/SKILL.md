---
name: diagnose-transport-loss
description: A MediaConnect flow is losing or dropping packets. Locate the failing source, flow, or output and state the viewer impact.
domain: mediaconnect
---
Goal: identify where transport loss starts, whether it is ongoing, and which downstream
outputs or viewers are affected. Tie every conclusion to a flow state, metric, or source
metadata field.

1. Call `describe_flow(flow_arn)` and record the flow state, source, outputs, and errors.
2. Call `get_source_health_metrics(flow_arn, hours_back=1)`. Check connection,
   disconnection, packet-loss, dropped-packet, not-recovered, ARQ, and merge metrics.
3. Call `get_output_health_metrics(flow_arn, hours_back=1)`. Compare output connection,
   dropped payload, late payload, and not-recovered metrics with the source.
4. Call `describe_flow_source_metadata(flow_arn)` when transport type, program metadata,
   or source messages can distinguish malformed input from network loss.
5. Decide:
   - source loss rises before output loss: the contribution path or sender is failing;
   - source is healthy but one output fails: that output path is failing;
   - source and every output disconnect together: the flow or shared network path failed;
   - evidence is empty or conflicting: say what is missing and do not invent a cause.
6. Answer impact first, then cite the metric names, peaks, time window, and affected path.
   End with the smallest next diagnostic or operational action.

Never call `start_flow` or `stop_flow` unless the operator asked for that change. The coordinator
handles approval; this skill never grants permission.
