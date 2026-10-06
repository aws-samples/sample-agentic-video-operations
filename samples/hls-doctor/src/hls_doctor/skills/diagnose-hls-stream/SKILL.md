---
name: diagnose-hls-stream
description: When viewers report playback problems on an HLS URL, inspect the presentation end to end and lead with the delivery evidence.
domain: hls
---
1. Run `inspect_stream` on the manifest URL first. It validates the playlists,
   probes delivery and ranks findings with their evidence.
2. Read the findings worst-first. Severity is impact; confidence is evidence
   strength. A single failed request is evidence, not a conclusion.
3. For a live presentation, follow with `watch_playlist`: frozen playlists,
   stale CDN generations and publication races only show up across reloads.
4. Follow one finding at a time with the narrow tools: `probe_http` for one
   URL's delivery, `probe_segment` for timestamps and codecs, `decode_scte35`
   for a cue payload, `compare_rendition_alignment` for lag or drift,
   `inspect_interstitial`, `inspect_ll_hls` or `inspect_content_steering` for
   those features.
5. Quote the finding's observations (status codes, timings, sequence numbers)
   in the diagnosis, then its playback impact, then the next probe.
6. If a tool reports that ffprobe, the Apple validator or the player probe is
   unavailable, say what is missing and continue with the other evidence.
