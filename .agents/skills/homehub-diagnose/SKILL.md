---
name: homehub-diagnose
description: Diagnose HomeHub runtime health, API behavior, house/activity mode selection, presence/camera evidence, ML lanes, override pressure, or recent service errors. Use for read-only investigation and post-change verification; do not use for unrelated implementation work.
---

# HomeHub Diagnose

Start read-only and inspect only the lane needed for the symptom.

- Health, API/device state, deploy regression, or connectivity: read
  `references/runtime.md`.
- Wrong house/activity mode, presence conflict, camera authority, ML/fusion, or
  override behavior: read `references/automation.md`.
- Recent warnings, tracebacks, service restarts, or a named log pattern: read
  `references/logs.md`.

Use current production evidence when the question is about live behavior; do not
infer runtime truth from code alone. Prefer bounded endpoints, journal windows,
and SELECT-only queries.

Explain the causal chain and uncertainty, classify the finding when possible,
and recommend the smallest next action. Do not restart services, change modes,
write devices, modify production data, or deploy unless the user separately
asks for that action.