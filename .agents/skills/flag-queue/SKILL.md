---
name: flag-queue
description: Capture or review durable HomeHub follow-up items when the user asks to flag, queue, list, drain, file, or dismiss work for later. Do not invoke for ordinary implementation notes.
---

# HomeHub Flag Queue

Use `C:\Users\antho\.codex\data\home-hub-flags.jsonl` as the durable queue when
present. Preserve history; do not delete old rows.

Capture a concise title, body, owner/label when known, source, timestamp, and
`pending` status. Capturing a flag does not create a GitHub issue.

When draining, check current open issues before filing to avoid duplicates.
File, dismiss, or skip according to the user's instruction and record the
result in the queue.

GitHub writes require the same authorization that applies to the current
session; a request to capture a flag alone does not authorize filing it.