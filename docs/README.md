# Home Hub Documentation

Use this page as the entry point for repository documentation.

## Sources of truth

- [`PROJECT_SPEC.md`](PROJECT_SPEC.md) — product behavior, architecture, APIs, services, deployment, and operational constraints
- [`ML_SPEC.md`](ML_SPEC.md) — ML lanes, promotion policy, telemetry, and model lifecycle
- [`GAMEDAY_SPEC.md`](GAMEDAY_SPEC.md) — game-day features and integrations
- [`PERSONALITY_LAYER.md`](PERSONALITY_LAYER.md) — personality, emotion, and mood behavior

## Architecture and design

- [`CONFIDENCE_FUSION.md`](CONFIDENCE_FUSION.md) — multi-source confidence and activity fusion
- [`PRESENCE_LIGHTING_SCENARIOS.md`](PRESENCE_LIGHTING_SCENARIOS.md) — presence and lighting expectations
- [`LIGHTING_EXPANSION.md`](LIGHTING_EXPANSION.md) — future lighting hardware and room coverage
- [`AGENT_STRATEGY.md`](AGENT_STRATEGY.md) — operational-agent strategy and retired monitoring loops
- [`Future_Development.md`](Future_Development.md) — longer-range ideas

## Incidents and audits

- [`INCIDENT_2026_07_DESKTOP_INACTIVE_LIGHTING.md`](INCIDENT_2026_07_DESKTOP_INACTIVE_LIGHTING.md) — lighting instability while Anthony was home but the desktop was inactive, plus its remediation plan
- [`REPO_CLEANUP_2026_07_31.md`](REPO_CLEANUP_2026_07_31.md) — cleanup inventory, deletion reasoning, retained local state, and regeneration commands
- [`archive/AUDIT_2026_05_05.md`](archive/AUDIT_2026_05_05.md) — archived full-system audit and resolved or deferred findings
- [`archive/Audit_Summary_2026-04-28.txt`](archive/Audit_Summary_2026-04-28.txt) — earlier archived audit summary

When behavior and documentation disagree, update the relevant source-of-truth spec as part of the implementation that changes the behavior.
