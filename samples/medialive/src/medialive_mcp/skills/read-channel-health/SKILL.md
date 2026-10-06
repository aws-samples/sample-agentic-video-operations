---
name: read-channel-health
description: Answer "is this MediaLive channel healthy?" with a short impact-first summary across the five health categories.
domain: medialive
---
Goal: one short answer an operator can act on, with every conclusion tied to a metric.

1. If no channel id was given, call `list_channels()` and pick the channel the operator
   named. Ask when two names match; never guess an id.
2. Call `check_channel_issues(channel_id, hours_back=1)`. Unless the operator asked for
   another window, use 1 hour, and never more than 24.
3. Read `status`: HEALTHY, WARNING (minor or recovered issues), DEGRADED (an issue is
   still happening) or CRITICAL (ongoing input loss over half the window). Lead with it.
   **HEALTHY:** report the state, the running pipelines and the overall score. Stop there.
   **NOT_EMITTED** (the whole channel or one category): CloudWatch has no datapoints, so
   health is unknown, not good. Say which metrics are in `not_emitted`; usually the input
   is absent or the channel is not producing output. Never report it as healthy.
4. **Issues found:** for each one, name the category, metric and pipeline. Read only the
   categories involved with `read_channel_metrics(channel_id, category=<category>)` to
   give the latest value and the peak.
5. When the issue is about content (black or frozen frames, slate), add
   `describe_channel_thumbnail(channel_id, pipeline_id)` for the affected pipeline.
6. Answer in this order: impact on viewers, the evidence (metric, value, pipeline,
   time), then the next step. For input loss, follow the `diagnose-input-loss` skill.

Don't list every metric. Keep it to what changed and what it means.
