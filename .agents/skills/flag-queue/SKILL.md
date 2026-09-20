---
name: flag-queue
description: Capture or process durable HomeHub follow-ups. Use when the user asks to flag, queue, list, drain, file, or dismiss work for later.
---

# HomeHub Flag Queue

The historical Windows 10 queue lived at
`C:\Users\antho\.codex\data\home-hub-flags.jsonl`. That file and the
entire old `.codex` data root are not present on the rebuilt Windows 11
machine. Do **not** invent or reconstruct old queue rows from memory.

Until Anthony explicitly establishes a new queue location, treat the durable
flag queue as unavailable rather than silently creating a replacement. If a new
queue is later authorized, label it as new Windows 11 state, preserve all rows,
and document its canonical path here.

For a live queue, capture a concise title, body, owner/label when known, source,
timestamp, and `pending` status. Capturing a flag does not create a GitHub issue.

When draining, check current open issues to avoid duplicates, then file, dismiss,
or skip according to the user's instruction and record the result. A request to
capture a flag alone does not authorize a GitHub write.
