# Lighting output vs. ScreenSync owner — offline pair prototype (2026-10-31)

**Status:** Non-actuating draft PR candidate, **not merged or deployed**. No runtime reader, continuous collection, or device write authority. The exact PR/commit and CI result are recorded in #244 and the PR, not assumed by this runbook. Issue [#244](https://github.com/agatte/home-hub/issues/244), related [#370](https://github.com/agatte/home-hub/issues/370), #136 and draft PR #387. Parent read-only single-snapshot foundation merged in [PR #433](https://github.com/agatte/home-hub/pull/433), master merge `7cd7d8f`.

## Why this slice

Nighttime underlighting cannot be conclusively attributed to authored brightness tables alone: watching ScreenSync can own L2/L5, manual per-light state and scenes can override, and a camera's brightness proxy is not human eye-level lux. Existing GET /api/automation/screen-sync/status exposes last_color_at, last_source, source_authority_enforced, authoritative_source, last_source_authoritative and authoritative_targets. It does **not** expose a same-frame final write token, per-light lease or Hue acknowledgement. The existing `/api/automation/pipeline` exposes the engine's `output.lights` last-applied cache; the pair comparison also reports its per-light on/brightness alongside actual Hue GET readings. Agreement is not a bridge acknowledgement, and disagreement can reflect stronger owner, an intentional scene, external-off, dedup cache staleness, or non-atomic GET timing. Comparing two sequential GET snapshots is **not atomic** and will not establish causality.

## Run explicitly offline

Generate **two operator-supplied JSON samples** collected no more than 120 seconds apart. Each entry must have a timezone-aware ISO8601 collected_at and a snapshot object containing fields already used by the merged read-only shadow adapter: automation_status, automation_pipeline, screen_sync_status, camera_status, lights, optional bedroom_lux. The pair analyzer does not fetch endpoints itself.

`python scripts/lighting_output_pair.py --frames <operator-controlled-input.json>`

The input's top-level format is:

```json
{
  "samples": [
    {"collected_at": "2026-10-31T20:00:00-04:00", "snapshot": {"automation_status": {}, "lights": []}},
    {"collected_at": "2026-10-31T20:00:03-04:00", "snapshot": {"automation_status": {}, "lights": []}}
  ]
}
```

That deliberately incomplete sample produces abstentions, **not** a useful assessment. The CLI outputs only whitelisted on/brightness, deltas, mode/period/house, short reason codes, the automation engine's whitelisted last-applied cache targets and reported ScreenSync source and target IDs; no raw images, credentials, window titles, source string payloads or personal timestamps in output. No disk history, daemon, scheduled sampling, new API, current lighting writes or background work. Operator must securely handle and dispose of *input* JSON: it can contain raw endpoint fields; use only synthetic fixtures until a separately reviewed snapshot-capture/retention policy exists.

The ScreenSync correlation flag requires non-empty consistent reported source/targets in both frames, source_authority_enforced and last_source_authoritative true, plus last_color_at no older than ten seconds and at most two seconds in the future relative to each observation. A backward-moving last_color_at timestamp across frames is an explicit abstention, even if both values are individually fresh. A changed source, changed mode/house/daypart, DND/scene/manual Activity/per-light override, non-Home, non-after-dark, disabled/unknown automation or invalid timestamps blocks technical hypotheses. Both frames must positively identify a fresh named Desktop Desk observation with fused Desk zone; missing attribution or fresh conflicting Latitude Couch/Bed evidence blocks findings. This is conservative diagnostic source filtering, not a grant of lighting authority. Even positive correlation is **not** Hue write causation or comfort evidence. Off fixtures are never proposed to relight; clear L5 is labeled glare-capped, not a substitute for diffused L2.

## Preview-only feedback (not intake or learning)

`python scripts/lighting_output_pair.py --feedback-snapshot <pre-feedback-snapshot.json> --rating too_dark`

Ratings: too_dark, comfortable, too_bright. The helper freezes a minimal **preceding** mode/daypart/house/ownership/on-brightness context and returns it to stdout with `learning_action=none_preview_only`; it does not save preferences, call a UI, learn, change light output or change any Activity. Future #131 work must separately authorize collection, privacy limits, per-action trust/demotion and corrections, rather than treating one rating as a global brightness floor.

## Important limits and next step

This is a testable source-attribution **hypothesis generator** using existing nominal status endpoints, not the more trusted named-source / final-write / lease / Hue-ACK diagnostic lane proposed under #370. No source truly proves fixture ownership, and the two GET reads can see different instants. Before physical lighting changes or passive collection, obtain independent review, establish true ScreenSync frame age and final owner/ACK evidence, verify Couch/projector and Bed provenance and protected/external-off/scene/manual authority, and physically calibrate warm diffuse L2 relative to clear L5 and living L1/L6 after dark. Retain #244 OPEN until real comfort acceptance; #270 redesign remains separate.

## Source checkout/reconciliation note

Protected Sandbox local canonical `main` was behind GitHub `master` when this candidate was prepared. The isolated test worktree was created from cached `9670b3f` and carries exact copies of merged PR #433 source files as local import dependencies. Publication must construct its tree directly atop the freshly verified GitHub `master`, include only these four new files and the shadow runbook status correction, and prove that the already-merged code files are not duplicated. Preserve the separate local worktrees and unresolved #370 draft PR #387.
