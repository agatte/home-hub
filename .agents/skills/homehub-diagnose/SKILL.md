---
name: homehub-diagnose
description: Diagnose live HomeHub behavior. Use for runtime/API, mode/presence/camera/ML/override, or recent service/log problems.
---

# HomeHub Diagnose

Start read-only and load only the reference for the implicated lane:

- Runtime/API/device/deploy/connectivity: `references/runtime.md`.
- House/activity mode, presence/camera, ML/fusion, overrides:
  `references/automation.md`.
- Recent warnings, tracebacks, restarts, or named log patterns:
  `references/logs.md`.

Use current production evidence for live questions; do not infer runtime truth
from code alone. Prefer bounded endpoints, journal windows, and SELECT-only data.

Explain the causal chain and uncertainty, classify the finding when useful, and
recommend the smallest next action. Live writes, restarts, or deploys remain
separate actions unless already authorized.
