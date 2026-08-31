# Documentation + GitHub Reconciliation — 2026-08-30

## Purpose

This checkpoint reconciles HomeHub repository documentation and GitHub issue state against canonical code and verified production behavior after the August 30 sensing/lighting/runtime deployments.

It exists because multiple generations of accepted decisions were preserved in docs and issues without consistently marking which later decisions superseded them. Historical evidence is valuable, but it must not read like current execution guidance.

## Evidence baseline

Canonical code baseline reviewed: `7107bda` (`Avoid repeated Brio reopen after lux sampling`). Relevant deployed lineage:

- `b49c687` — promote Latitude YOLO person authority and Desktop Desk/Bed localization.
- `f41bcda` — keep the morning ramp in color-temperature space instead of HSB hue interpolation.
- `7107bda` — keep the Brio webcam handle open after healthy lux-sample recovery; recycle only on failed/black recovery.

Production validation associated with that lineage included a broad `882 passed, 1 expected skip` regression pass before the Brio hotfix and a subsequent hotfix broad pass of `753 passed, 1 expected skip`, plus live verification of YOLO readiness, Desktop Desk evidence, CT-mode lights, and stable Brio handle behavior.

## Authority hierarchy

When sources disagree, use this order:

1. Current canonical code plus verified production/runtime evidence.
2. `docs/PROJECT_SPEC.md` for cross-system product/system truth.
3. `AGENTS.md` for repository execution/safety guidance.
4. Current subsystem specs for their owned domain.
5. Current GitHub issue body/checkpoint for remaining scope and sequencing.
6. Dated audits, incidents, calibration notes, rejected branches, and old issue comments as historical evidence only.

## Repository documentation audit

All 32 tracked Markdown files were included in the audit scope, including root/tooling READMEs and dashboard devtool docs rather than only the top-level `docs/` directory. Non-Markdown documentation artifacts were also reviewed: `HomeHub_Travel_Mode_Design.docx` remains an explicitly unimplemented design proposal; the archived April audit TXT remains historical; and the Apartment Canvas JSON/SVG contracts remain preserved machine-readable inputs/baselines rather than being casually rewritten during a docs pass. Under #192, stronger evidence may intentionally supersede old physical-coordinate/fingerprint claims through the physical source model and its derived artifacts.

Current-authority documents reconciled in this branch include:

- `AGENTS.md`
- `README.md`
- `docs/PROJECT_SPEC.md`
- `docs/ML_SPEC.md`
- `docs/CONFIDENCE_FUSION.md`
- `docs/PRESENCE_LIGHTING_SCENARIOS.md`
- `docs/Future_Development.md`
- `docs/GAMEDAY_SPEC.md`
- `docs/LIGHTING_EXPANSION.md`
- `docs/DASHBOARD_APARTMENT_CANVAS_SPEC.md`
- `docs/LOCAL_WORKSPACE.md`
- `docs/README.md`
- `frontend-svelte/devtools/apartment-canvas-preview/README.md`
- `frontend-svelte/devtools/apartment-whitebox/README.md`
- `requirements-camera-shadow.txt` comments, because the filename is historical but the pinned OpenVINO runtime now supports deployed authority.

Other Markdown files were reviewed and left unchanged when they were already current, clearly historical, or intentionally scoped to a preserved design/audit snapshot.

## Current sensing truth

- Latitude real-person authority is YOLO26n-pose/OpenVINO-gated.
- MediaPipe alone cannot manufacture physical presence from furniture.
- After YOLO confirms a real person, trusted MediaPipe evidence may supply conservative Couch localization; YOLO presence alone does not mean Couch.
- Latitude confidence `<=0.01`, model unavailability, or inference failure is unknown/blinded rather than explicit absence.
- Desktop is the calibrated bedroom locator: accepted close face is Desk evidence; calibrated distant-pose geometry may commit Bed after dwell; ambiguity abstains.
- Bed location does not imply Bed posture, Sleeping, Watching, Working, or Morning.
- `PresenceFusion` is the live physical-zone arbitration layer; trustworthy physical conflicts resolve by freshness.
- `activity_events.zone/posture` is not fused physical truth: `EventLogger` still snapshots the Latitude `CameraService` directly, so current Desktop Desk/Bed is not written into those columns.
- The rejected fixed-X `0.52/0.53` Latitude Couch experiment remains evidence only and must not be resurrected as current policy.

## Current lighting/runtime truth

- The morning ramp uses brightness + CT (`ct=400 -> 250`) and no longer interpolates HSB hue through green/cyan (`f41bcda`).
- Desktop lux sampling restores/verifies auto exposure on the existing Brio handle and only recycles when recovery fails or becomes effectively black (`7107bda`).
- The Windows Blue Yeti path is the active ambient-audio source; the former Latitude microphone path is disabled.
- The Windows PC-agent supervisor has a Scheduled Task ACL boundary under non-elevated recovery. Use the verified identity-safe workflow; do not infer successful replacement from a PID-only kill/launch.
- `home-hub.service` is the normal backend restart target. Do not manually restart `home-hub-ambient.service` as part of ordinary HomeHub deploy/recovery work.

## Apartment Canvas authority

GitHub #192 is the current physical-world authority for Apartment Canvas object size/placement, anchors, provenance, and evidence-backed corrections.

Pre-#192 GeometryScene fingerprints, plan-space XY guardrails, whitebox geometry, and production-preview artifacts remain useful visual/projection baselines, but they cannot veto an accepted #192 physical-model correction. Presentation camera/cutaway choices remain distinct from physical-world truth.

## GitHub reconciliation

Current issue contracts/checkpoints updated during this pass:

- #198 — deployed YOLO-gated Latitude authority; open only for bounded real-room Couch acceptance.
- #201 — deployed Desktop Desk/Bed localization; open only for bounded real-room Bed acceptance.
- #80 — owns cleanup/reconciliation of dormant Latitude-era bed+posture automation, not deletion of current Desktop `zone=bed`.
- #142 — roadmap checkpoint refreshed to the August 30 shipped/current state.
- #154 — remains open; physical-evidence path-light guards improved, but projector-safe ScreenSync/final-cap policy remains unresolved.
- #200 — remains open and fully current: Latitude loopback still posts the obsolete `regions` schema and accepted Latitude media intent still injects synthetic Couch occupancy into `PresenceFusion`.
- #202 — sensing prerequisite now exists, but real-room Bed acceptance and separate fixture/period comfort-envelope calibration still gate production actuation.
- #146 — remains the separate Desktop FaceLandmarker suspend/resume semantic-health defect; the Brio lux-handle hotfix does not close it.
- #56 — narrowed to Desktop **Desk posture** calibration only if current evidence shows a failure; it no longer owns Desk-vs-Bed location or the retired Latitude bedroom plan.
- #25 — lifecycle observability now explicitly treats Desktop Bed as location evidence only, never Sleeping or a sleep-quality signal.
- #45 — reframed from an expired preseason task to evidence-driven regular-season stakes enrichment with safe fallback.
- #149 — Travel remains an accepted design proposal, not implemented runtime behavior; current Blue Yeti audio and Windows supervisor/service boundaries replace proposal-era host assumptions.
- #13 / #137 — hardware/inference dependencies now record #147 as completed L6 / Plant Wash and evaluate kitchen/path behavior against the current YOLO/Desktop physical-evidence stack.
- #160 — re-audited against canonical `7107bda`: the current lockfile still reports 13 npm audit findings (1 low / 6 moderate / 6 high / 0 critical), but the lockfile/advisory baseline has advanced beyond the old August 18 commit. The issue remains an exposure-classification task, not a blind upgrade instruction.
- #105 / #203 / #204 — dated `7477ca4` Gaming observations remain historical calibration evidence; August 30 comments explicitly record `7107bda` as current canonical and require reinspection before implementation.

## Historical material intentionally retained

Dated audits, incidents, calibration checkpoints, rejected candidate branches, and old issue comments remain valuable evidence. They should retain the facts observed at the time. Reconciliation should add authority/status context rather than rewrite historical measurements to look current.

Examples include the August 1 autonomy audit, August 18 Dashboard UX audit, August 28 context-lighting ownership audit, #198 fixed-X calibration history, YOLO shadow-bakeoff checkpoints, and pre-#192 Apartment Canvas visual baselines.

## Known current gaps after reconciliation

- #198 real-room Couch acceptance after YOLO promotion.
- #201 real-room Bed acceptance after Desktop localization promotion.
- #200 laptop loopback schema mismatch + synthetic media-to-physical occupancy leak.
- #154 remaining projector-safe nighttime Watching/ScreenSync policy.
- #202 later calibrated Bed comfort envelope.
- #146 FaceLandmarker suspend/resume semantic-health recovery.
- #160 frontend dependency advisory classification/remediation decisions.
- #137 bounded current-system kitchen/path inference trial before any #13 sensor purchase.
- `activity_events` camera enrichment still reflects Latitude CameraService rather than fused Desktop/Latitude physical location.

## Maintenance rule

When a shipped change supersedes an earlier design, update the current-authority section and GitHub checkpoint in the same workstream. Keep old evidence dated and explicitly historical. Avoid using “accepted,” “current,” or “production” in preserved design artifacts unless their authority scope is unambiguous.
