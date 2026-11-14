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

## PROPOSED ONLY: offline single-light policy (#461, 2026-11-03)

`backend/services/quiet_atlas_one_shot_contract.py` is an unregistered pure
assessment model, with synthetic tests in `tests/test_quiet_atlas_one_shot_contract.py`.
It accepts exactly one absolute power OR brightness (1–254) target. No route,
writer, ownership acquisition, operation identity or completed-command claim
exists. Even `eligible` is advisory only and always `permits_write=False`.
This is **UNAPPROVED policy**, not an accepted PROJECT_SPEC decision.

| Observed owner / state | Proposed native handling (UNAPPROVED) |
| --- | --- |
| Ordinary known unowned, fresh, available fixture | May be advisory eligible |
| Manual stamp | Decision required; overall product must allow repeated manual adjustments, but native handling needs approved same-intent ownership semantics |
| Fresh source-qualified ScreenSync | Decision required; explicit handoff/release, no automatic takeover |
| Transit, scene/effect, known external owner | Decision required; explicit handoff/release |
| Unknown owner or unavailable/unqualified/stale observation | Unavailable, fail closed |
| Protected fixture, Away/external-off/host-return, Sleeping, disabled automation, pending scene/transition, DND | Blocked pending reviewed policy |

All safety facts must be explicitly known. Target errors precede observation
shape/identity/source/age checks, then availability/unknown owners, then hard
safety gates, then manual/ScreenSync/transit/scene/effect/external conflicts.
The proposed freshness ceiling is strictly less than five seconds, using supplied
monotonic times; future times fail closed. A trusted server adapter must qualify
both telemetry and owner evidence in one coherent snapshot. Client REST receipt
time is never sufficient. The offline enum does not authenticate provenance.

Changed evidence requires reassessment; no result reserves authority or closes
a race. Future integration must reuse `LightingTransitionBoundary.serialized()`,
`LightingAuthority` currency and `AutomationEngine.validate_lighting_lease()` at
delegated mutation, rather than add another lock/token or reuse legacy PUT's
write-then-stamp path. No integration is implemented here. Remaining gates are
owner policy approval, trusted adapter/freshness policy, commit-time race and
idempotency handling, acknowledgement/persistence and physical readback.
Legacy working controls must remain available; these proposed restrictions
must not create permanent lockout. No takeover, deployment or physical
convergence is approved or demonstrated by these offline tests.

## Source-only WebSocket guard candidate (2026-11-13; NOT APPROVED FOR RELEASE)

The existing HomeHub `light_command` path (used by legacy `LightCard` and
draft #529's in-flow room reveal) formerly wrote to Hue before marking manual
ownership, without checking the shared final-write lease. In the isolated
`work/461-ws-manual-authority-20261113` development branch, a **candidate**
`backend/services/ws_manual_light_guard.py` now routes that existing command
through `LightingTransitionBoundary.serialized()` and
`run_write(validator=...)`, with a pre-queue per-light authority lease,
post-read revalidation and the existing HueService final dispatch rendezvous.
It denies unknown fixture identity, inaccessible/unreachable bulbs, stale
source generations, Away/Sleeping, external-off/host-return, active scene or
effect, transit, ScreenSync, protected/external owners and unknown legacy owner
notifiers. A second manual adjustment can continue while ordinary manual
ownership remains current, but **no stronger-owner takeover is implied**.
The command is single-fixture only; this changes neither scenes nor group
fanout. Transport ACK, ownership persistence and post-stamp authority currency
are treated separately; ambiguous outcomes are not retried or reported as
physical confirmation.

**Local synthetic evidence only:** 13 focused offline test cases passed,
including 28 parametrized owner/lifecycle subcases, a directly invoked
FastAPI WebSocket handler (without lifespan), and a real HueService
dispatch/circuit-breaker implementation with a fake bridge; Ruff and
`git diff --check` also passed. These are not physical Hue observations.
The branch remains separate from draft #529 and is not in production.

**Still blocking any high-risk integration/deployment:** the Svelte
`setLight` client optimistically updates its shared store and receives no
per-command rejection/acknowledgement, so a denied command could temporarily
look successful. REST `PUT /api/lights/{id}` and other direct writers still
need their own authority reviews; this WS candidate does not grant a new
one-shot API or durable server operation-key/idempotency contract. Repeated
250ms slider writes plus pre-write Hue inventory reads need latency/bridge-load
acceptance, and owner-policy review still must resolve live Travel/DND evidence
and per-light bedroom glare ceilings. Physical readback, source freshness,
disconnect/restart, cross-client collision, kiosk/iPhone usability, and
operator acceptance remain unverified. **No live host/device write or
approval to merge/deploy has been given.**

### Correlated WebSocket result (draft #530 follow-up; source-only)

A new `light_command` may optionally carry `command_id` (8–64 safe ASCII
characters). The value is correlation **only**: it is not authentication,
authorization, a durable operation key or idempotency. The endpoint advertises
`light_command_results: true` in its existing connection handshake and sends
`light_command_result` only back to the same requesting WebSocket with
`command_id`, validated fixture ID and one status: `acknowledged` (Hue
transport ACK + completed manual ownership persistence), `denied` (no write
authorized), `unavailable` (unreachable/unknown bridge or fixture),
`uncertain` (physical outcome or ownership durability not provable), or
`invalid` (schema rejection with safely echoed ID). Commands without IDs
remain backward compatible. No result is a physical readback.

Draft UI PR #529 gates its redesigned room controls on the explicit handshake
capability, sends *one* final drag command, matches only the latest in-flight
result per fixture, and displays denial/unavailability/uncertainty visibly.
A missing/older server never receives the new tracked room command, and
disconnection/timeouts never trigger automatic retries. Original Apartment
controls remain on their separate legacy behavior. The server's rate limit may
reject a frame before parsing its correlation ID; a client must treat a missing
result as **uncertain**, not assume a non-write. Neither PR is a substitute for
review of the REST light writer, physical readback or approved release.

### Source-only REST manual writer closure (2026-11-13; NOT AUTHORIZED TO MERGE)

A bounded fake-bridge investigation showed `PUT /api/lights/{id}` could
report `status=ok` after issuing a Hue call without evaluating
`validate_lighting_lease`. The initial WebSocket-only guard did not protect
this existing REST path. The current **unreleased** #530 development update
routes the single-fixture REST PUT through `dispatch_manual_light` with the
same serial boundary, pre-queued lease, final Hue dispatch fence, ownership
stamp and persistence confirmation. Only registered L1–L6 fixture IDs can
be commanded; CT/HSB mixing is rejected. Accepted PUTs preserve the legacy
`{"status":"ok","light_id":...}` shape, while preflight denied, unavailable,
and physically uncertain outcomes are separated (409/503/409 respectively).
An uncertain outcome specifically instructs the caller to inspect the actual
bulb rather than retry blindly. Event logging failure cannot retroactively
report a successful write as failed.

The owner's REST brightness step (`POST /api/lights/brightness/{up,down}`)
and manual bulk action (`POST /api/lights/all`) also previously dispatched
direct Hue commands. They now reuse the **per-fixture** guard. They report
`status=partial_failure` with explicit `updated`, `blocked`, `unavailable`
and `uncertain` fixture lists if any individual outcome is not verified as
a bridge ACK plus durable manual owner stamp. A missing automation engine
fails closed. The bulk action no longer directly calls
`HueService.set_all_lights` or emits immediate mid-transition WebSocket
broadcasts; the existing Hue polling/EventStream paths report device state.
An unknown newly discovered Hue fixture cannot join the manual group action
merely because the bridge exposes it. This is **not an atomic all-fixture
transaction**: earlier acknowledged bulbs are not automatically undone when
a later bulb is denied or uncertain. Do not retry a partial batch blindly.

Draft #529's legacy All Off card has a source-only UI update to indicate
partial/uncertain results, disable repeated clicks while pending, and avoid
claiming physical confirmation on successful transport ACK. The server's
full per-fixture scene/effect pipeline is **not** replaced; explicit managed
scene operations retain separate ownership and physical acceptance gates.

Local fake-only evidence at this checkpoint: 52 focused REST/WebSocket tests
passed, plus 28 parameterized owner/lifecycle cases and 222 broader authority,
manual-hold, authentication and tunnel-proxy regression tests. Ruff and
`git diff --check` passed. These numbers are *local developer evidence*,
not hosted CI nor real bulbs. The expanded REST/UI changes are not shipped.

**Required risk review before high-risk integration:** Per-fixture bulk
sequencing may be slower and partly applied compared to prior parallel Hue
writes; actual Hue inventory freshness, bridge load, 20s All Off UI timeout,
readback, older API consumers, authenticated client trust boundaries and
Cross-Client/ScreenSync/effect transitions need operational testing. The
WebSocket endpoint's inherited unauthenticated/Origin-unvalidated surface
remains tracked by security issue #284; this change does not address that
finding. DND is documented as blocking autonomous changes while allowing
explicit user actions, and must not silently become a blanket manual ban.
No live host or Hue write, deployment, merge, or physical acceptance occurred.

### Manual writer dedup/cache reconciliation — source-only safety refinement

A shared-authority manual Hue write also needs to reconcile the engine's
`last_applied_per_light` automation dedup state. Without that step, an
acknowledged manual adjustment could leave the previously automated target
cached as if it still matched the bridge, and the post-expiry/mode-change
reconciliation might dedup-skip the needed restore.

The guarded writer therefore records an acknowledged manual mutation through
the existing `AutomationEngine.record_leased_light_write`, **after** marking
manual ownership (so target inference can read the old cached base) and
**before** the fresh persistence checkpoint. This evicts that fixture's
automated dedup record without stealing stronger ScreenSync ownership. On an
uncertain write or late owner conflict, it calls
`AutomationEngine.forget_ambiguous_light_write(...,
preserve_screen_sync=True)` while the existing lighting boundary remains
held. This clears only uncertain cached state, not owner/physical status,
and never retries the Hue command. Fake-boundary regression tests assert
both accepted and ambiguous cache invalidations and deny any false manual
stamp. The refined change is **not physical confirmation**.

These changes still require exact-head CI, independent ownership review,
separately approved high-risk merge and Latitude deployment, then witnessed
real fixture and kiosk/iPhone acceptance. Do not infer those gates from the
earlier green CI on the unrefined guarded writer.


### #461 offline final synthetic integration ? November 14, 2026

Local uncommitted implementation evidence only: target
`C:/Work/home-hub-project/worktrees/qa-461-final-synthetic-20261114`, branch
`work/461-final-synthetic-20261114`, base
`1f5d296e2c8f0504b8718ceedfaba89b1a961b8a`. No GitHub publication or
operational/owner acceptance is implied.

The original A composite was applied from its binary working diff and exact
untracked paths. B's reviewed remediation delta was applied relative to
`2d502864207012701a07c2aafc5a03b919adc2f5`. Patch overlaps in `LightCard.svelte`,
`stores/init.js`, and `ws.js` were reconciled using B's HEAD as the three-way
base. The receipt transport's boolean return merged automatically; the card
and store required explicit synthesis. Home keeps individual L1?L6 controls,
capability gating, pending/denied/uncertain receipt feedback and one explicit
brightness command on release. Classic retains rapid local input composition;
both use observed shared fixture state and version-fenced rejection readback.
Home's receipt ID is passed through the remediation command tracker so the
same private result settles both paths. ACK never fabricates physical state.

The Node tests execute the actual component handlers and store wiring with
synthetic transport, reads and timers. Added overlap coverage verifies inline
drag release/cancellation, pending suppression, correlated denial, stale-read
fencing, ACK semantics and disconnect without replay. A's older bulk tests
were reconciled with B's approved incomplete-inventory behavior: absent
canonical fixtures remain unavailable, and only a complete acknowledged
L1?L6 set returns success. The first combined Python run exposed six stale
assertions (619 passed and 32 subtests passed); the corrected bulk suite
passes 17 tests, including a full-six-fixture success case.

C's four boundary/projection source and test files are byte-identical copies
from `ws-native-projections-293-20261114` at
`6dda871be9c53f2a82f4cbeb21305f8007533472`. Neither security module is imported
by live `backend/main.py`; live `/ws` remains anonymous with the manual-write
guard and private receipts. No authentication cutover or credential change
was made.

Source preservation was verified using exact command-scoped safe.directory
reads: identical HEAD, branch, complete porcelain status and SHA-256 hashes
for all changed/untracked source files (A: 45; B: 11; C: 4). A remains detached
at the target base. No source or Windows main writes were performed.

Remaining gates: full frontend CI/build and real iPhone/kiosk acceptance;
#287 provisioning, browser/iPhone/kiosk cookie issuer, TLS and native client
credentials; #296 real Hue fixture identity; separate authorization for
high-risk integration/merge, production deployment and physical witness.
The next safe gate is an offline full frontend CI/build in an already
provisioned environment, without installation or runtime activation here.


Final combined validation in the target: **626 Python tests passed, 32
subtests passed, zero failures** (195.55s). One existing Starlette/httpx
deprecation warning; no dependency installation was attempted. The selection
ran `test_ws_authenticated_boundary`, `test_ws_native_projection`,
`test_ws_identity_policy_proposal`, `test_ws_manual_light_guard`,
`test_rest_manual_light_guard`, `test_hue_fixture_identity`,
`test_quiet_atlas_one_shot_boundary_contract`, `test_lighting_authority`,
`test_lighting_final_write_authority`, `test_manual_light_persistence`,
`test_hue_bulk_failclosed`, `test_hue_response_validation`, and
`test_identity_foundation` together. Invocation used the existing main venv's
absolute Python path, `-B`, `APP_ENV=testing`, `PYTHONDONTWRITEBYTECODE=1`,
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `-p pytest_asyncio.plugin` and
`-p no:cacheprovider`.

**58 Node tests passed, zero failures/skips**, using the approved absolute
Node executable with `--test` on `tests/node/lightCard.test.mjs`,
`tests/node/lightCommands.test.mjs`,
`tests/unit/lightCommandReceiptTracker.node.mjs` and
`tests/unit/quietAtlasDefaultCutover.node.mjs` under `frontend-svelte`.
Ruff `check --no-cache` passed on all 20 touched Python paths; tracked diff
and explicit untracked whitespace, UTF-8 and conflict-marker checks passed.
Full frontend CI was not run: no frontend node_modules or installation/network
authority was available. These are offline contract results, not physical,
production-health, hosted-CI, or owner-acceptance evidence.


#### #461 synthetic frontend completion — November 14, 2026 (local, not CI or live)

The same uncommitted synthetic target was subsequently checked with a *locally
copied* preprovisioned `frontend-svelte/node_modules` tree, not new packages,
downloads, host installations or source-branch edits. The source
`apple-artist-browser-431-20261104` dependency tree had the **same SHA-256
package-lock.json** as the rehearsal target. All generated files remained in
the isolated target worktree.

- `@sveltejs/kit/svelte-kit.js sync`: exit **0**.
- `svelte-check --tsconfig ./jsconfig.json`: exit **0**, **0 errors,
  0 warnings** on the complete combined frontend.
- `vite build`: exit **0**, static adapter wrote `frontend-svelte/build`;
  root entry, client assets and `/classic` route bundle generated. The
  `untrack`, `fork` and `settled` export warnings arise from optional
  Svelte 5 APIs while this project uses Svelte 4.2.20 and Kit 2.70.3;
  inspected Kit source guards the calls/falls back. This is an offline build,
  not live browser hydration/phone acceptance.
- Full default Vitest run `vitest run --maxWorkers=2`: **342 passed, 2
  failed** (57 test files) on the initial combined target. Both failures
  were stale source-text assertions about `LightCard` internals, not
  runtime failures: the reviewed final-write path uses
  `dragPowerOn = !light.on || controlTarget.on === false` and handles
  `pointercancel` / `lostpointercapture` via `onPointerEnd` and
  `cancelGesture()`, which clears delayed writes, pending state and
  optimistic preview before flushing. Only the two target-only unit tests
  were updated to assert those existing safeguards (no app-code changes).
  Both affected files were rerun: **9/9 passing**, exit 0. All other
  default-suite tests passed on unchanged application code. A second entire
  57-file run was intentionally not repeated.
- Independent `vitest.hue-browser.config.js` run: **3/3 passing**, exit 0.
- Earlier combined offline results remain **626 Python passed + 32 subtests**
  and **58 dependency-free Node passed**. Ruff, UTF-8,
  conflict-marker and whitespace checks passed.

**Release interpretation:** Source-level frontend build/check verification is
now achieved for this combined candidate. It remains **uncommitted,
unpublished, unmerged, undeployed, and NOT operationally validated or
owner-accepted**. Live `/ws` is still anonymous. The next gating work is
the reviewed #287/#293 real identity broker, browser/iPhone/kiosk secure
cookie/session issuance (including kiosk TLS), native credential migration
and protected outbound event contract; #296 Hue fixture/certificate evidence
and physical L1–L6 verification; a newly integrated exact-head CI review;
then separately approved high-risk integration and production deployment.
Physical kiosk/iPhone lighting acceptance is the original completion gate.
Do not deploy or merge the synthetic branch as-is.


### #293 source integration follow-up (November 14, 2026; NOT DEPLOYABLE)

In `work/293-ws-cutover-20261114` at base
`1f5d296e2c8f0504b8718ceedfaba89b1a961b8a`, the anonymous `/ws` route and
raw manager broadcast path are now removed **in this unmerged branch only**.
All snapshots, producer broadcasts and private #530 receipts use the existing
authenticated boundary with explicit scoped projection and per-send fresh
authorization. With no separately supplied trusted broker/issuer configuration,
ordinary startup rejects before accept and emits no initial state. No real
broker/session issuer or credential is created; production is unchanged.

The current contract, complete fixed producer/consumer inventory, known dropped
events/fields and remaining operational gates are recorded in
[SECURITY_IDENTITY_FOUNDATION.md](SECURITY_IDENTITY_FOUNDATION.md#293-authenticated-runtime-source-cutover).
The redesigned Home controls keep their existing capability, observed-state,
private correlation, version-fenced rejection readback and no-retry semantics.
ACK still means transport plus manual-owner persistence, never physical readback.
Browser pre-accept denial preserves disconnected/unavailable UX. Existing
lighting and Sonos final ownership handlers remain in the authenticated path.

This is executable offline source engineering, not completed #287/#293 or
kiosk/iPhone acceptance. Deployment is blocked by the separate OS broker,
secure browser/kiosk/native credential delivery and TLS/client migration,
missing event compatibility contracts, exact-head review/CI and separately
approved integration/deployment/physical witness. No source A/B/C or original
synthetic target, credentials, host/device runtime, service or retirement changed.


Offline validation for this WS cutover: **669 Python tests + 32 subtests passed**;
final affected route/concurrency run **41/41 passed** (one extra cancellation
case beyond the combined collection); existing dependency-free Node **58/58
passed**. Ruff, diff and explicit untracked text checks passed. Full frontend
CI/browser/physical trials were not run in this target; no frontend source or
dependencies changed. Full invocation/evidence is in the linked identity section.
