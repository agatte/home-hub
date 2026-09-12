---
name: flag-queue
description: Capture or process durable HomeHub follow-ups. Use when the user asks to flag, queue, list, drain, file, or dismiss work for later.
---

# HomeHub Flag Queue

Use `C:\Users\antho\.codex\data\home-hub-flags.jsonl` when present. Preserve
history; do not delete old rows.

Capture a concise title, body, owner/label when known, source, timestamp, and
`pending` status. Capturing a flag does not create a GitHub issue.

When draining, check current open issues to avoid duplicates, then file, dismiss,
or skip according to the user's instruction and record the result. A request to
capture a flag alone does not authorize a GitHub write.
