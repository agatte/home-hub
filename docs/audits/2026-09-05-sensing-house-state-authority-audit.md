# Sensing / House-State Authority Audit - 2026-09-05

## Status

Read-only bounded audit against canonical baseline `4694a81` (`Update Codex operating policy`). The audit used one explicitly approved Astra Low worker, with no implementation, tests, service calls, hardware access, or production mutations. The audit worktree remained clean.

Raw worker output is preserved outside the tracked repo at `snapshots/astra-sensing-house-state-audit-20260905.txt`. This note preserves reviewed conclusions; `docs/PROJECT_SPEC.md` remains authoritative for accepted product decisions.

## Confirmed code-level findings

### 1. Weak Latitude process evidence can end Sleeping

`AutomationEngine.report_activity()` currently lets a process activity above Idle wake non-override Sleeping. `LatitudeStreamingDetector` can emit Watching from playback alone, so passive/background Latitude playback can satisfy that gate without human-wake evidence. This conflicts with the accepted Sleeping contract. Production occurrence was not established by this audit.

### 2. Physical return can split AwayManager and AutomationEngine authority

`CameraService` may call `AutomationEngine.signal_presence("camera")`, which clears engine Away/external-off suppression without clearing/persisting `AwayManager._away`. After a missed geofence ARRIVE, runtime can therefore behave Home while persisted occupancy still says Away; a restart can resurrect stale Away, and a later LEAVE can be dismissed as a duplicate. Production occurrence was not established by this audit.

### 3. Latitude media retraction can leave Watching authoritative

Latitude Idle is correctly treated as a media-intent retraction rather than global Idle, but `_finalize_process_report(... disposition="retracted")` removes the accepted semantic without recomputing the incumbent authoritative mode. Watching can therefore persist after its Latitude evidence is gone until another path replaces it. Existing tests encode part of this split. Production occurrence was not established by this audit.

### 4. Explicit Sleeping -> Auto wake authority is not restart-durable

`clear_override()` sets `_home_awake_confirmed=True` for explicit wake, but that latch is not persisted with override/lifecycle state. A backend restart can lose the confirmed-awake authority and allow residual Sleeping/device evidence to reclaim old overnight behavior. Production occurrence was not established by this audit.

## Accepted product decisions after review

Sleeping -> Home authority is source-qualified: explicit human wake intent wins immediately; validated fresh Apple Watch/Apple Health wake evidence may win immediately; fresh trustworthy interactive semantic activity (for example active desktop Working/Gaming or genuinely interactive Watching) may win immediately; passive Latitude playback, PC/device wake, stale semantics, and similar software residue abstain. Cameras remain off during established Sleeping for privacy.

Apple Watch/Apple Health begins as an observation/confirmation lane. Manual Sleeping remains primary. After several representative nights validate latency, freshness, false positives, and brief-wake behavior, sustained Watch sleep evidence plus compatible inactive/bedtime context may graduate to automatic Sleeping as a fallback for nights when Sleeping was not manually selected. Higher-consequence shutdown actions remain separately gated.

Home-after-wake and Morning-confirmed are separate. A brief overnight wake may become Home with subdued time-appropriate behavior and later return to Sleeping without starting the full Morning experience.

Away/Home occupancy is owned only by `AwayManager`. Strong fresh physical person evidence from either trusted camera establishes/retains Home even when the person may be a guest. ARRIVE establishes Home immediately. LEAVE establishes departure unless contradicted by new post-LEAVE physical person evidence; stale pre-LEAVE evidence does not veto departure. Weak software/device activity and absence-only evidence have no occupancy authority. Persisted occupancy and engine suppression must transition together.

## Work tracking

- #155 is completed historical lineage for explicit Sleeping -> Auto. Follow-on findings 1 and 4 plus the accepted interactive-wake boundary are tracked in #235.
- #236 owns Apple Watch / Apple Health delivery, shadow calibration, graduation criteria, and later automatic-Sleeping fallback.
- #237 owns finding 2: Away/Home occupancy reconciliation with AwayManager as the single persisted lifecycle owner.
- #238 owns finding 3: Latitude media retraction/handoff, related to but distinct from #143 Watching credibility, completed #189 process-semantic separation, and #200 Latitude media/physical-occupancy separation.

## Highest-value next implementation step

Define one durable Sleeping/wake authority boundary in code and tests before further detector-specific patches, while separately repairing AwayManager as the single persisted occupancy owner. Do not couple either change to production deployment without its own authorization and runtime verification gate.
