# #370 Desk L2 trusted input / final-owner integration design (offline only)

> **Status:** local non-actuating design and review packet, 2026-10-23,
> consolidated with the classifier/tests for review; not committed or published.
> **Current candidate base:** draft PR #387 head
> `677191d6f6e3550a1e68f9bd0cb7792edc3ea395`, tree
> `2838f21e27c3953904ff8fbdf89015d370f2d044` (byte-identical to
> local Sandbox base commit `c1489c65f72e3e87958910508275bc7317c7ba1a`).
> The original independent review used earlier `670abe3`/tree `a72390d`
> before the already-published source-readiness packet advanced the PR.
> **Owner:** Lighting & Atmosphere #370. Dependencies: #136/#244 physical
> calibration, #243 ScreenSync color/owner fidelity, Sensing & Intelligence.
> **No caller, sensor adapter, dispatched payload or write authority is implemented.**

## Decision for the next implementation lane

Retain the **single existing** pure offline
`backend/services/desk_visual_comfort.py::resolve_desk_diffuse_l2_candidate`.
The competing unpublished `desk_diffuse_eligibility.py` worktree is preserved,
not imported or given production callsites. Its stricter-input tests informed
the separate reconciliation packet already published on draft PR #387.

Treat every Boolean supplied to `DeskDiffuseL2Context` as an **attestation**
which an eventual trusted runtime adapter must prove from the *named source*
and original owner. The helper itself only bounds an **already authorized,
already-on** L2 brightness proposal; it neither verifies sensor provenance nor
mints an owner lease. The following are proposed integration acceptance
conditions, **not claims that the adapter currently exists**.

## Source and house evidence (read-only candidate adapter)

1. **House/awake:** engine internal `house_state == "home"` must be explicitly
   mapped to exact external contract `"Home"`; **not** by blindly calling
   `.title()` on unknown states. Gate out Away, Winding Down, Sleeping, off,
   host-return hold, DND, and independent manual/scene/transit/protected/away
   ownership before allowing a candidate. A manually chosen semantic Activity
   does not itself authorize or veto L2; explicit per-light manual control does.
2. **Physical Desk:** call
   `PresenceFusion.get_source_reading("desktop")` and assert
   `reading.source == "desktop"`, `zone == "desk"`,
   `face_present is True`, `detection_source in {None,"face"}`, and bounded
   capture age. Existing `AutomationEngine` desk-ownership paths use
   `-2 <= age_s <= PHYSICAL_CONTEXT_OBSERVATION_FRESH_SECONDS` (currently 8s).
   Reject conflicting fresh, strongly present Latitude Couch/Bed. Weak generic
   `latest_zone()`, `is_at_desk_fresh()`, desktop **process** activity and
   software Gaming/Working cannot satisfy this authority for a relight.
   Negative/future ages require the existing bounded clock-skew rule and
   independent source validation; never treat a negative age as indefinitely
   fresh. Input provenance and physical fallback remain separate from
   semantic source selection.
3. **Viewing:** require an independently eligible desktop screen-viewing
   signal with freshness and device/source attribution. User Activity, monitor
   power or ambient lux cannot create a fictitious physical Desk or qualify
   a view. Do not infer screen content from a semantic mode.
4. **Bedroom lux:** use only `LuxChannel("bedroom")` driven by the accepted
   desktop-lux route and matching calibration source. The existing
   `AutomationEngine._read_fresh_bedroom_lux()` checks baseline and the
   channel's `is_fresh(300)`, but returns only two floats; it **does not
   provide** all of the proposed trust/room/source attestations. An eventual
   adapter must independently check matching room/source identity, finite
   nonnegative EMA, finite positive calibrated baseline, accepted UTC timestamp
   (reject unbounded future age), freshness and sample/calibration continuity.
   `LuxChannel.is_fresh()` checks only `age <= max_age_s`; do not mistake it
   for future-skew rejection. A baseline's existence is **not** #136/#244
   verification of a comfortable L2 lighting floor. The separate
   `_read_fresh_camera_lux()` living-room camera path cannot qualify bedroom
   evidence.
5. **Floor and effective cap:** do not invent a numeric value, lux-to-nit
   translation or calibration period. Only an accepted period-specific L2
   floor and actual current effective owner cap can reach the pure resolver.
   Original L2 `on=True` and positive brightness must derive from the
   **current applicable branch owner's composed target**, not an older Hue
   readback, previous acknowledged frame or stale cache. Watching's frame/cap
   path and Gaming's accepted target path are distinct. Unknown original
   brightness, owner or effective cap must abstain. A cap below the original
   means reject the uplift, never independently authorize dimming. No relight
   of off/manual-off and no L5 brightness uplift.

## Ownership and commit points — no new write route

- **Static:** a fresh source snapshot and the **actual**
  `LightApplicator.protected_light_ids()` / current override/effect/external
  owners must agree; static abstains if ScreenSync currently owns L2. The
  `AutomationEngine._apply_mode` revision/source guard is captured across
  awaited composition, and `LightApplicator._write_many(static=True)`
  revalidates per-light static authority in the shared
  `LightingTransitionBoundary`. A stale mode/physical epoch or new owner
  must drop the proposed lift, never retry it as an unguarded write.
- **ScreenSync:** never let static composition rewrite an actively leased
  ScreenSync-owned L2. A candidate for the accepted owned frame could only
  be composed **inside** `ScreenSyncService._leased_frame` and its existing
  frame-sequence, frame-age, lease and authority validator. However, the
  wrapper's frame sequence and acceptance age **do not prove capture-frame
  identity or provenance**. Before any future integration, bind accepted
  source, capture timestamp, frame generation/sequence, original frame target
  and resolved branch-specific cap. Missing binding must abstain, never set
  `same_frame_guard_guaranteed=True` from the wrapper alone. The existing
  `AutomationEngine.validate_screen_sync_lease` delegates to the canonical
  `validate_lighting_lease`; do not issue an independent floor lease.
- **Final boundary:** only the already-owned Hue chokepoints can dispatch:
  `LightingTransitionBoundary.serialized()` and delegated write validators
  are retained across cancellation and worker settlement; `HueService`
  rechecks the inherited validator **immediately before bridge entry**, not
  atomically with a physical Hue invocation. Once a bridge call has started,
  cancellation or later supersession **cannot guarantee no physical write**.
  Existing revision and lease validators also do not directly revalidate
  elapsed physical observation age, bedroom lux/calibration continuity or DND.
  Unknown effect authority and pending Gaming-scene transitions are additional
  named vetoes. Any future integration must supply explicit evidence/deadline
  guards and reject stale calls **before entry**, then conservatively reconcile
  ambiguous in-flight acknowledgement. Proof must cover owner generation ABA,
  stale physical source/lux, manual/per-light/scene/transit,
  DND/Away/Sleeping/external-off, ScreenSync supersession and cancellation.
  Original off remains off even when a proposed floor is above zero. No
  monitor, kitchen L3/L4, L5, hue/sat/CT, Game Day or separate actuator may
  be changed by this lane.

## Known traps verified from the checked-in implementation

| Existing API | What it actually proves | What it **does not** prove |
| --- | --- | --- |
| `PresenceFusion.latest_zone()` | Best merged source zone, with some legacy desktop compatibility | Fresh strong **desktop** face with no opposing Couch/Bed |
| `PresenceFusion.get_source_reading("desktop")` | Last named source reading | Acceptable freshness/conflict or true physical viewing |
| `LuxChannel.ema_lux`, `is_fresh()` | Calibrated-baseline existence and upper age limit | Finite values, bounded future skew, calibration provenance or comfortable L2 floor |
| `DeskDiffuseL2Context.transition_epoch_current` | Caller assertion | Current serialized write ownership (old snapshot can be reused) |
| `LightApplicator.protected_light_ids()` | Static mode per-light safety snapshot | New ownership that begins **after** the snapshot |
| `ScreenSyncService._leased_frame` | Frame/lease authority only while its current boundary is held | Future independent static writer authorization |

## Offline test and integration gate

Existing adjacent regression suites to verify before any adapter edit:
`tests/test_presence_fusion.py`, `tests/test_lux_channel.py`,
`tests/test_lighting_final_write_authority.py`,
`tests/test_desk_l2_contract_reconciliation.py`, and
`tests/test_desk_diffuse_l2_policy.py`.
They cover existing source, temporal, ownership/race and pure-policy surfaces,
**not end-to-end #370 floor integration**.

Any future trusted adapter needs new deterministic negative fixtures for
old/future/unqualified desktop face; simultaneous strong Latitude Couch/Bed;
missing/stale/nonfinite/wrong-room lux; scene/manual/DND/suppression takeover;
ScreenSync same-frame mismatch and mode/owner ABA after an await; cap-below-
original and originally-off L2. Tests must prove that a proposal **cannot**
outlive fresh source evidence or the final authority epoch. Review this packet
against current repository state and run independently in Sandbox before
proposing any runtime caller.

**Physical activation gate remains closed** until lived twilight/night
L2/L5 + monitor-to-room calibration under #136/#244, an accepted bounded
hysteresis/ramp, an independently reviewed owner/final-write implementation,
separate integration authorization and separately approved deployment/device
writes. A fully green draft-PR CI does not close those product/physical gates.
