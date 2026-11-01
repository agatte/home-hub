# Quiet Atlas Control — proposed actuation contract (#270)

> **Status: PROPOSED; NOT APPROVED FOR ACTUATION OR DEPLOYMENT.**
> Dashboard UI owns presentation and interaction acceptance; Lighting & Atmosphere /
> House State own the backend writer, ownership and transition safety.
> This note does not authorize any Hue/scene/device write. Existing production
> dashboard and separate Apartment page retain their contracts.

## Established from current source (2026-10-31)

- Quiet Atlas `/quiet-atlas/control` uses an opt-in, read-only REST snapshot;
  a recent `GET /api/lights` response timestamps receipt **at the frontend**.
  It is **not evidence of recent bridge telemetry, active ownership, fixture
  availability at commit, or permission to write**. WebSocket light state may
  be optimistic and is not a safe substitute.
- `GET /api/scenes` exposes declared `lights` targets for curated presets
  and custom scenes. These declarations may be useful **only as intended
  composition previews**. They are not current bulb states or guaranteed final
  effects; the scene writer may retain protected targets or apply effects.
  Native Hue bridge scenes lack a reliable per-light manifest in this route.
- `PUT /api/lights/{id}` (backend/api/routes/lights.py) and websocket
  `light_command` (backend/main.py) issue bridge writes and *then* stamp/persist
  manual ownership. Neither currently returns a scoped commit-time guard,
  monotonically fenced precondition or physical readback acknowledgement to a
  frontend caller. Therefore directly enabling `Apply` based on frontend
  `recent-read` would overstate safety and can race newer owners.
- `POST /api/scenes/{id}/activate` uses `_activate_scene_safely` and the
  lighting transition boundary with acknowledgement/ownership handling.
  Native scenes have unknown declared scope and conservative postactivation
  readback. This existing backend path must not be bypassed or reproduced by
  a UI-side group fan-out.
- UI visual groups are **not device-control groups**. Bedroom L2/L5 are
  independently calibrated for glare and perceived output; Kitchen L3/L4 may
  differ in custom and atmospheric scenes.
- Current source already provides reusable **process-local** infrastructure:
  `LightingAuthority.issue()/valid()/invalidate()` publishes global and
  per-light monotonic generations, `LightingTransitionBoundary.serialized()`
  fences physical transitions, and `run_write(validator=...)` rechecks at
  delegated mutation. `AutomationEngine.validate_lighting_lease()` checks
  protected owners and lifecycle/scene restrictions **inside** that boundary;
  a lease alone is freshness evidence, **not permission**. Existing tests
  `test_lighting_authority.py` and `test_lighting_final_write_authority.py`
  cover the shared mechanism with fake bridges (79 tests passed 2026-11-01).
  Reuse these rather than invent a competing lock/owner token. Any future
  new route must decide which user-intent takeovers, if any, may override
  manual, ScreenSync, scene or transit ownership; default is reject.
- Scene-list reads also need their **own** connection/visibility generation.
  Dropping a selected review on disconnect is insufficient if a stale
  in-flight `GET /api/scenes` can repopulate the selectable list after
  reconnect. This read-only client invalidates earlier results on these
  boundaries and refreshes before showing newly trusted scene metadata.

## Proposed minimum safe one-shot control

1. The operator selects an individual light (not a whole visual group), makes
   a percentage or power selection, and reviews which fixture will change.
   The preview may express percent as Hue brightness 1–254, but must never
   assume that a read-only receipt authorizes actuation. Do not send repeated
   drag writes or patch optimistic global light state before acknowledgement.
2. **Server-owned preflight / commit-time authority is a dependency, not a
   client-constructed token.** Backend must run the final owner/transition
   policy under the relevant serialized lighting boundary. A fresh bounded
   read is necessary but not sufficient. Explicitly check connected bridge,
   fixture identity/reachability, host Away/Travel/RETURNING_HOME/external-off,
   Sleeping, stronger scene/transit/manual/ScreenSync and protected-light
   owners, pending transitions, and freshness of any owner observations.
   Product semantics for intentional manual takeover of a current
   ScreenSync/transit/scene owner require review by those workstreams;
   do not silently overwrite or automatically claim ownership.
3. An accepted one-shot command must bind its expected fixture, requested
   state, owner/scene generation and idempotent operation identity to the
   commit-time check; reject stale/conflicting proposals explicitly (e.g.
   409) **before** the physical write. Do not retry an ambiguous write without
   an idempotency contract. Explicitly separate `conflict`, `unavailable`,
   `failed`, `sent/not confirmed` and `confirmed`.
4. Only the established backend writer performs the bridge action; stamp and
   persist manual ownership consistently with the transition boundary.
   Never mix CT with HSB in one Hue payload. Reconcile readback and delayed
   WebSocket broadcasts without post-write brightness snapback or duplicated
   light writes. A transport `200` is not physical confirmation.
5. For curated/custom presets, show **declared** fixture targets (On/Off,
   brightness where explicitly provided) and an effects/ownership warning,
   then use only the guarded existing scene transition path after separately
   approved preflight. For native scenes with unknown manifest, require an
   explicit broad-effect warning and a guarded native-scene transition.
   Preserve scene/try-it cancellation leases and manual-ownership semantics.
6. During unmount, disconnection, visibility loss or changed fixture/scene
   metadata, invalidate any pending preview. If a physical command was
   already sent, do not imply cancellation undid it; reconcile by fresh
   authoritative read and surface an indeterminate result if needed.

## Required deterministic and physical acceptance before enabling writes

- Simulate races: reconnect, stale GET, wrong fixture, duplicate click,
  overlapping slider edits, acknowledgement timeout, late GET/WS echo,
  backend retry, scene handoff, newer manual owner, ScreenSync freshness,
  transit and scene owner takeover, external-off/Away, Sleeping/Travel,
  pending transition, protected L2/L5 glare limits and Kitchen pair divergence.
- Backend race/fault tests must prove **zero bridge writes on denied preflight**
  and preserve owner generations and persisted overrides on ambiguous results.
  A simple REST key check or client `connected` boolean is not sufficient.
- Browser acceptance at 320px, phone, tablet and desktop must verify
  accessible focus, readable percentages, pending/error/retry states and
  zero unintended network writes; physical Latitude/phone and evening
  L2/L5 calibration must be separately approved and explicitly observed.
- Deliver via reviewed branch/CI, then **separately approved** merge,
  deployment via `scripts/deploy.sh`, device actions and final physical
  acceptance. Merged code does not imply it runs on Latitude.

## This slice's permitted change

The Quiet Atlas preset review may render **declared** curated/custom targets
from `GET /api/scenes` while continuing to show unknown native scene
effects and leaving all actuators absent. This is a useful evidence preview
for eventual confirmation UX, not a claim of readiness to turn on writes.
