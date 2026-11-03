# #370 — Offline source-observation readiness and read-only diagnostics

**Status, 2026-10-23:** source-observation classifier and tests published
to [draft PR #387](https://github.com/agatte/home-hub/pull/387) at
`ad39278ab57d7c98541ffd847e61b5daecf345b9`, full Git tree
`0f2fbfbed3ce988e1c3d311de09e13ddb174619c`. Both exact-head Linux CI
workflows passed all six jobs. This follow-up adds only a strictly
authenticated read-only diagnostic route and tests; no runtime deployment or
light actuation is authorized.
Earlier independent classifier and owner-provenance reviews remain valid only
within their explicitly assessed non-actuating scopes.
The existing PR publishes the advisory classifier; this subsequent
change adds only a read-only camera diagnostics API consumer.
There is still **no AutomationEngine/ScreenSync lighting composer caller**,
changed lighting target, Hue/DDC/agent/host action or write capability.

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


## Follow-up: read-only named-source diagnostics (no deployment)

A narrow subsequent candidate adds
`GET /api/camera/desktop/l2-observation-readiness` under the existing
`require_api_key_strict` dependency. Non-localhost private-LAN callers need
an API key; this does not change any existing camera route. It reads the actual `app.state.presence` and
`app.state.bedroom_lux` objects, using only source-specific
`get_source_reading("desktop")` and `get_source_reading("latitude")` and the
calibrated bedroom `LuxChannel`. Unexpected/missing stores fail closed. The
endpoint returns `status`, `scope="advisory_observation_only"`, the two
readiness flags, ordered reason codes, and `lighting_authorized=false`.

This is a **diagnostic consumer, not a trusted sensor identity adapter**:
normal incoming camera POST auth supports configured LAN bypass, source strings
are not cryptographically bound to a physical sensor, the current LuxChannel
does not carry per-sample exposure/calibration continuity attestations, and a
labelled calibrated baseline is not a measured comfortable L2 floor. The
endpoint does not attest House Home/awake, DND, manual/scene authority, actual
screen content or same-frame ScreenSync ownership/cap. Its flags must NEVER
be promoted to `DeskDiffuseL2Context` write-authority attestations.

The endpoint does not expose raw face, timestamps, image frames, ambient lux,
baseline or owner details and sets `Cache-Control: no-store`. It computes no
Hue target, transition, payload or lease. Synthetic in-process HTTP tests
verify 401 without an API key and 200 with an API key from a private-LAN
client. A separate privacy/security review remains necessary before release.
Deterministic tests cover the strict authorization dependency, real producer
stores, opposing Latitude Couch, wrong room, stale/future readings and no
producer mutation.
