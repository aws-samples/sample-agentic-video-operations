---
name: diagnose-signal-path
description: When viewers see a problem and the cause may be upstream, walk the signal path from MediaConnect flow to MediaLive channel.
domain: coordinator
---
0. Resolve the affected resource ARN, then call
   `list_workflows(contains_arn=<affected ARN>)`. If one stored workflow contains it,
   call `get_workflow(workflow_id)` and use that latest version as the path of record.
   If several match, ask which workflow to use. Fall back to the steps below only when
   no stored workflow exists. Never guess links that differ from a stored path.
1. Find the affected MediaLive channel and read its health. Note the input it is on.
2. If the channel shows input loss, or no packets on its input, the fault is upstream.
3. If the mediaconnect tools are loaded, find the flow that feeds that input and read
   its source health: packet loss, recovered packets, round-trip time, source state.
4. If the problem is in the picture itself (frozen, black, slate, soft), use the
   `assess-picture-quality` skill to measure it and confirm it with the encoder's signals.
5. Conclude at the first hop that is unhealthy. The hops after it inherit its fault.
6. If a hop cannot be read (no tool loaded, permission denied), say the path is unverified
   from that hop on, and name the missing evidence.
