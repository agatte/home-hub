# Home Hub Documentation

Use this page as the entry point for repository documentation.

**Last repository/GitHub truth reconciliation:** August 30, 2026. See [`DOCS_GH_RECONCILIATION_2026_08_30.md`](DOCS_GH_RECONCILIATION_2026_08_30.md) for the reviewed evidence and remaining known gaps.

## Document ownership

- [`PROJECT_SPEC.md`](PROJECT_SPEC.md) is the single authoritative source for
  cross-system product direction, experience policy, architecture, and
  roadmap. Its August 14, 2026 Product Experience Contract distinguishes
  `SHIPPED/CURRENT`, `DECIDED TARGET`, `RESEARCH NEEDED`, and `DEFERRED`.
- `SHIPPED/CURRENT` requires current committed-code evidence; where deployment
  matters it also requires reliable deployment/current-state evidence, and a
  health claim requires explicit production verification. Dated repository
  records alone do not establish current capability or health.
- Subsystem specs own detailed design and implementation constraints within
  their domain, while deferring to `PROJECT_SPEC.md` for cross-system policy:
  [`ML_SPEC.md`](ML_SPEC.md), [`GAMEDAY_SPEC.md`](GAMEDAY_SPEC.md),
  [`GAMING_EXPERIENCE_SPEC.md`](GAMING_EXPERIENCE_SPEC.md),
  [`PERSONALITY_LAYER.md`](PERSONALITY_LAYER.md), and
  [`PRESENCE_LIGHTING_SCENARIOS.md`](PRESENCE_LIGHTING_SCENARIOS.md).
- [`DASHBOARD_REDESIGN_VISION.md`](DASHBOARD_REDESIGN_VISION.md) owns the active
  Dashboard UI/UX target language and information-architecture direction for
  #157 while deferring cross-system policy to `PROJECT_SPEC.md`.
- [`Future_Development.md`](Future_Development.md) is a concise,
  non-authoritative idea and GitHub-issue index. Its entries and issue labels
  do not set roadmap priority.
- Dated incidents, audits, investigations, and cleanup plans are historical
  evidence. Preserve their original conclusions; add a current-status note or
  canonical cross-reference instead of rewriting history.

## Architecture and design

- [`DASHBOARD_REDESIGN_VISION.md`](DASHBOARD_REDESIGN_VISION.md) — active Dashboard redesign vision: living apartment canvas, contextual hierarchy, semantic motion, Analytics/inference-machine language, mobile/desktop composition, and explicit rejected precedents
- [`GAMING_EXPERIENCE_SPEC.md`](GAMING_EXPERIENCE_SPEC.md) — schedule-aware, game-specific Gaming presentation, fixture roles, bounded telemetry effects, and calibration policy
- [`CONFIDENCE_FUSION.md`](CONFIDENCE_FUSION.md) — multi-source confidence and activity fusion
- [`PRESENCE_LIGHTING_SCENARIOS.md`](PRESENCE_LIGHTING_SCENARIOS.md) —
  historical presence/lighting decisions and subsystem implementation detail
- [`LIGHTING_EXPANSION.md`](LIGHTING_EXPANSION.md) — current expansion plan and installed L6/Plant Wash record; later hardware remains planned
- [`HomeHub_Travel_Mode_Design.docx`](HomeHub_Travel_Mode_Design.docx) - historical accepted proposal/reference for the Latitude HOME/TRAVEL contingency lifecycle tracked by #149; V1 HOME/TRAVEL/RETURNING_HOME behavior is shipped, while #145 now designates the Latitude as the always-home core and current runtime truth lives in `PROJECT_SPEC.md` plus the host-control code
- [`AGENT_STRATEGY.md`](AGENT_STRATEGY.md) — operational-agent strategy and retired monitoring loops
- [`Future_Development.md`](Future_Development.md) — non-authoritative issue
  and idea index

## Incidents and audits

- [`DASHBOARD_UX_AUDIT_2026_08_18.md`](DASHBOARD_UX_AUDIT_2026_08_18.md) — dated pre-redesign Dashboard UI/UX audit and issue-reconciliation evidence; target direction now lives in `DASHBOARD_REDESIGN_VISION.md`
- [`INCIDENT_2026_07_DESKTOP_INACTIVE_LIGHTING.md`](INCIDENT_2026_07_DESKTOP_INACTIVE_LIGHTING.md) — lighting instability while Anthony was home but the desktop was inactive, plus its remediation plan
- [`REPO_CLEANUP_2026_07_31.md`](REPO_CLEANUP_2026_07_31.md) — cleanup inventory, deletion reasoning, retained local state, and regeneration commands
- [audits/PRODUCTION_AUTONOMY_EVIDENCE_AUDIT_2026_08_01.md](audits/PRODUCTION_AUTONOMY_EVIDENCE_AUDIT_2026_08_01.md) — dated, read-only production/autonomy evidence snapshot and implementation handoff
- [`archive/AUDIT_2026_05_05.md`](archive/AUDIT_2026_05_05.md) — archived full-system audit and resolved or deferred findings
- [`archive/Audit_Summary_2026-04-28.txt`](archive/Audit_Summary_2026-04-28.txt) — earlier archived audit summary

When code, production, and documentation disagree, record the evidence level
explicitly. Update `PROJECT_SPEC.md` for cross-system policy changes, update the
owning subsystem spec for implementation-detail changes, and do not use a
future issue or historical incident as proof of current behavior.
