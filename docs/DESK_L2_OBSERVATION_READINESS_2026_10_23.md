# #370 — Offline source-observation readiness classifier (local candidate)

**Status, 2026-10-23:** uncommitted Sandbox-only test/prototype consolidated
with the design document for review, based on current draft PR #387 head
`677191d6f6e3550a1e68f9bd0cb7792edc3ea395` and exact tree
`2838f21e27c3953904ff8fbdf89015d370f2d044`. Prior independent
implementation review was on the earlier but content-equivalent source tree
`a72390d1ee4a0769dea11391db9c82ebc35f48d8`.
No production importer, AutomationEngine/ScreenSync caller, changed lighting
target, Hue/DDC/agent/host action or final write capability.

The single existing `desk_visual_comfort.resolve_desk_diffuse_l2_candidate`
remains the unwired L2 policy; this module is **not a second eligibility
resolver**. `assess_desk_l2_observations` accepts explicitly supplied
`PresenceReading` source snapshots and `LuxChannel` bedroom reading, plus
caller-supplied timezone-aware `now`. It returns only frozen observations and
ordered rejection reasons. `authorizes_lighting` is **always False**,
including when both source observations pass.

| Evidence | What local classification checks | Not established |
| --- | --- | --- |
| Desktop Desk | source == desktop, face_present exactly True, zone desk, face/legacy detection type, -2..+8s capture age | Route identity, ongoing presence, viewing evidence, semantic authority |
| Latitude Couch/Bed | fresh stronger physical conflict veto using existing PresenceFusion strong-source rule | All geometric disagreement or future physical motion |
| Bedroom lux | channel room name bedroom, existing baseline presence, finite positive baseline, finite nonnegative EMA, -2..+300s timestamp window | Authenticated Desktop POST identity, calibration attribution/continuity, camera accuracy, comfort floor |
| Snapshot replay | Always advisory and re-evaluatable with supplied newer observations | A monotonic lease, final-writer epoch, ScreenSync source/frame/cap identity |

The classifier intentionally does **not** invoke a scene, change house state,
mint a lease, call a writer, calculate a Hue target, feed a positive assertion
to `DeskDiffuseL2Context`, or alter shared `LuxChannel.is_fresh` behavior.
A caller cannot substitute its `desktop_observation_ready` for trust in the
live source: source identity and timestamps originate outside this classifier.

Independent read-only design review (Sandbox Codex task
`9714a86756a746a98d6fbc4f2bdb7302`) found no P1 and four P2
specification gaps, now corrected in the consolidated
`docs/DESK_L2_OWNER_PROVENANCE_DESIGN_2026_10_23.md` document.
The source worktree remains preserved separately:
- ScreenSync's `_leased_frame` freshness/sequence are **not proof of source
  capture-frame, original target or effective cap binding**. A future adapter
  must explicitly bind all and abstain if unavailable.
- Original brightness/effective cap require provenance from the *applicable
  branch owner* (Watching vs accepted Gaming); prior Hue readback is not proof.
- Existing mode/lease guards do not include direct DND or lux capture-expiry
  validation. Require new bounded evidence guards at the accepted point.
- Hue pre-bridge-entry validator is not atomic with invocation and cannot
  revoke an already in-flight physical write; ambiguous acknowledgements
  must be reconciled conservatively.

This classifies evidence readiness **only**. It cannot close the #136/#244
physical night/twilight screen-to-room L2 floor and glare calibration, DND
policy, ScreenSync cross-frame owner race, hysteresis/ramp, or the separate
integration/deploy/device-action gates. The earlier source-readiness
packet is already published at PR #387 head `677191d6`; its clean worktree
`desk-370-source-readiness-20261023` remains preserved. The *unpublished*
competing helper in `desk-370-eligibility-20261023` also remains untouched;
this candidate does not introduce that duplicate policy.
