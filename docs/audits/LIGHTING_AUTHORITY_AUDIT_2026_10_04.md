# HomeHub Lighting Authority & Lifecycle Audit — 2026-10-04

> **Status:** Dated read-only architecture/correctness evidence. Not product authority and not a live-production claim.
> **Primary audit model:** GPT-6 Astra until Codex usage exhaustion after 118,376 tokens.
> **Independent verification:** GPT-5.6 Sol against the same Sandbox checkout.
> **Repository baseline:** `b6a286f0c5069a01cf43f029fd8a8dc07c82ec8d` (`master`).
> **Product authority:** `docs/PROJECT_SPEC.md`.
> **Current execution guidance:** `docs/EXECUTION_MAP.md`.
> **Owning issues:** #322 sunrise ownership, #323 final-write authority, #324 Away/off convergence, #246 manual-ownership persistence.

This document preserves the final synthesis from the October 4 lighting audit. It intentionally excludes private model reasoning and raw tool traces. Re-check current code, owning issues, and live device evidence before executing any packet.

---

## 1. Executive assessment

HomeHub's lighting authority architecture is **conditionally safe with a strong central compositor and a small number of semantic side doors**.

The central path is materially stronger than a collection of ad-hoc Hue calls:

- `LightApplicator` serializes writes through the shared transition boundary.
- It re-checks Away/external-off suppression and protected-light ownership.
- Manual, transit, ScreenSync and registered external-owner protections are composed centrally.
- Per-light success/failure is tracked rather than assuming whole-group success.
- Effect release reconciles back to current authoritative targets.
- ScreenSync has source/freshness ownership rather than a static capability list.
- Game Day delayed choreography performs per-step lifecycle/protected-light checks and reconciles afterward.

The recurring defect is narrower:

> **Mechanical serialization is more centralized than semantic final-write authority.**

Several special/delayed producers decide they are eligible before an `await`, sleep, bridge acknowledgement delay, or blocked transition boundary. They can then mutate Hue after a newer manual/lifecycle/scene/ScreenSync owner has won.

The right correction is to extend the existing lighting architecture with a **final-write authority generation/lease** rather than creating a second ownership framework.

No Critical finding was justified.

---

## 2. Canonical lighting architecture observed

### Shared transition/write path

The strongest ordinary path is:

`AutomationEngine / owner -> LightApplicator -> transition boundary -> HueService -> bridge`

Important properties:

- protected-light computation composes manual, transit, ScreenSync and external-owner state;
- Away/external-off suppresses ordinary application;
- deduplication is explicit and invalidated when the bridge may have diverged;
- CT and HSB fields are kept separate;
- effect release can restore the current owner rather than a hard-coded old baseline.

### Ownership dimensions

Observed authority dimensions include:

- lifecycle/Away/external-off suppression;
- per-light manual ownership;
- transit/navigation ownership;
- ScreenSync fresh source ownership;
- registered external owners such as League;
- scene/effect transition ownership;
- Game Day transient choreography;
- fixture/context comfort caps;
- mode/activity composition.

These dimensions are not interchangeable. Authentication/security identity must not become lighting authority.

### Final-write gap

The transition boundary answers:

> “Can this Hue operation run without mechanically interleaving another participating transition?”

It does **not** by itself answer:

> “Is the state computed before I waited still authorized now?”

Issue #323 owns that missing semantic contract for delayed/transient writers.

---

## 3. Findings

### High — scene “Try It” can restore a stale whole-apartment snapshot

Evidence: `backend/api/routes/scenes.py`, approximately lines 900-1017; delayed direct restoration occurs around the snapshot-revert writes near lines 927/971.

The route snapshots current light state, activates the temporary scene, sleeps about 30 seconds, then directly restores the old snapshot.

Credible sequence:

1. user starts Try It;
2. during the delay, user changes a light, selects another scene, returns to Auto, or lifecycle changes to Away/Sleeping;
3. the old trial task wakes and restores the pre-trial snapshot;
4. the restore bypasses current-owner reconciliation.

Away is especially problematic: an old trial can re-light after Away correctly turned lights off and armed suppression.

**Owner:** #323.

**Required architecture:** trial generation/lease. Revert only if the trial still owns the affected lights; otherwise discard stale snapshot intent and reconcile current authority.

### High — sunrise ramp bypasses changing authority for the full run

Evidence: `backend/services/morning_routine.py`, approximately lines 128-169; direct Hue write inside the delayed loop around line 161.

The routine checks DND once, then performs roughly 15 delayed direct Hue writes across about 30 minutes.

It does not re-check at each step:

- Away/external-off;
- DND changes;
- manual ownership;
- ScreenSync/protected lights;
- scene/effect/transit ownership;
- later lifecycle authority.

A scheduled sunrise can therefore continue to illuminate after stronger authority appears. Initial Away is also not a complete start guard.

**Owner:** #322, related product owner #139.

**Required architecture:** each delayed step must use an explicitly owned application path and revalidate immediately before mutation. No catch-up writes after cancellation/restart.

### High — Away may not converge all lights to OFF after partial Hue failure

Evidence: `backend/services/away_manager.py` around the hard-off path near line 733; `backend/services/hue_service.py::set_all_lights()` around lines 264-270.

Away suppression is established before the whole-home off request, which is correct. However, `set_all_lights()` gathers individual writes and collapses them to aggregate success. The Away path does not retain per-light unresolved state.

If one light fails while the rest turn off:

- Away suppression remains authoritative;
- the failed light may remain on;
- ordinary automation is intentionally suppressed and may not converge it later.

**Owner:** #324.

**Required architecture:** per-light OFF acknowledgement, bounded retry/reconnect handling, and generation fencing so a stale Away retry cannot run after a newer Home lifecycle wins.

### Medium — ScreenSync can apply and refresh ownership from a frame that became stale while waiting

Evidence: `backend/services/screen_sync.py::_set_light_serialized()`, approximately lines 886-894, plus source-write freshness recording after a successful mutation.

ScreenSync performs strong source/mode/manual/protected checks before the write. If another transition owns the boundary, ScreenSync waits. Once the lock becomes available, it writes the previously accepted frame without revalidating current mode/owner.

A successful stale write then refreshes ScreenSync freshness, so the stale frame can temporarily become protected from ordinary composition.

**Owner:** #323.

**Required architecture:** carry authority generation into the transition boundary; re-check before Hue mutation and refresh ScreenSync ownership only when that check succeeds.

### Medium — Rust flinch restore can overwrite authority acquired during the hold

Evidence: `backend/services/rust_event_service.py`, approximately lines 149-205; dip/restore around lines 180/199.

Ingress is correctly bounded to Rust gaming, and lights already manually held at flinch start are skipped. During the hold, however, mode/Away/manual/ScreenSync/protected authority can change. Restore does not re-check after the sleep.

Existing tests cover “manual before flinch,” not “manual/lifecycle takeover during flinch.”

**Owner:** #323.

### Medium — native Hue scene ownership can stamp the wrong state after acknowledgement delay

Evidence: `backend/api/routes/scenes.py`, native scene activation around lines 653-690.

After native v2 scene activation, HomeHub deliberately waits about 0.5 seconds, then reads the bridge and stamps manual ownership. A newer automation transition can occur in that gap; the later bridge read can capture the newer state and mark it as the user's manual scene intent.

**Owner:** #323.

**Required architecture:** retain scene ownership/generation through acknowledgement rather than inferring authority from an unguarded delayed snapshot.

### Medium/Low — partial v2 effect start can desynchronize tracker and physical state

`HueV2Service.set_effect_all()` performs multiple writes and returns aggregate success. If some lights start the effect and one fails, the effect manager can retain a “known/no active effect” interpretation while physical lights are partially in the effect.

Existing effect reconciliation is otherwise strong.

**Backlog:** keep in this audit unless #323 naturally supplies the needed partial-result/generation contract. Promote only if implementation evidence shows a separate fix is required.

### Low — whole-home direct light endpoint remains an unowned side door

The `/api/lights/all` path performs a whole-home direct fan-out without the same explicit manual-ownership semantics as ordinary per-light control. No active in-repo caller was found during the audit.

**Backlog:** harden/retire if still exposed after the broader security/lighting work; do not create another issue solely from static reachability without current use evidence.

---

## 4. Hypotheses checked

### Confirmed

- sunrise delayed writes can override later authority;
- direct/special low-level Hue write exceptions exist outside the canonical applicator;
- ScreenSync can become semantically stale while waiting for the shared boundary;
- delayed scene trial work can write after newer manual/lifecycle authority;
- Rust restore can write after ownership changes during its hold;
- multi-light partial failure can leave physical state inconsistent with lifecycle intent.

### Rejected or substantially narrowed

#### Sleep fade is not a general stale-task defect

Mode changes and explicit Sleeping-to-Auto wake paths cancel the sleep fade. Fade writes use `LightApplicator`, so Away/manual/transit/ScreenSync/protected-light rules remain active.

#### Game Day delayed lighting is comparatively strong

Game Day re-checks lifecycle/sequence authority and the shared protected-light gate immediately before delayed steps, then reconciles back to current steady state. Preserve this pattern as a reference contract.

#### League external ownership is integrated

League uses the registered external-owner model and has explicit release/reconciliation tests. The audit did not find a broad League ownership bypass comparable to the delayed side doors above.

#### Restart does not resurrect most transient owners

ScreenSync, Rust, League and similar transient claims are memory-scoped. The separate restart issue is the opposite problem: still-valid manual ownership is lost across restart (#246).

#### Hue SSE reconciliation is not proven to permanently misclassify self versus external writes

The v2 stream has an in-flight suppression/reconciliation discipline and normal polling fallback. An external physical change may be delayed during an in-flight window, but this audit found no static evidence of permanent false ownership from that mechanism.

---

## 5. Existing test quality and gaps

Current coverage is substantial around the central architecture:

- `tests/test_lighting_ownership_regressions.py`;
- `tests/test_effect_transition_boundary.py`;
- ScreenSync route/service tests;
- Away manager tests;
- Game Day celebration tests;
- Rust event tests;
- Hue v2 focused tests.

The main gap is **authority changing while a side-door writer is waiting**.

Required deterministic additions:

- block the transition boundary, change mode/owner, release it, prove stale ScreenSync frame does not mutate or refresh ownership;
- start Try It, supersede with manual/Away/Sleeping/new scene, advance fake clock, prove no stale snapshot restore;
- start Rust flinch, supersede during hold, prove no restore;
- native scene acknowledgement with a newer transition during the 0.5s wait;
- sunrise with every relevant owner/lifecycle guard changing between delayed steps;
- Away partial failure, bridge reconnect, restart, and Home-generation supersession;
- partial effect-start reconciliation if still unresolved after #323.

Use fake Hue/device implementations and fake clocks/barriers. Real bridge writes are not needed for implementation validation.

---

## 6. Issue routing

### Existing owners

- **#322** — sunrise final-write ownership; related to #139 Morning.
- **#246** — persist still-valid manual per-light ownership across restart.
- **#251** — completed cross-Activity fixture-comfort boundary; preserve its accepted caps/authority.
- **#253** — Game Day delayed-write behavior is a useful reference implementation.

### New bounded issues from this audit

- **#323 — Lighting authority: revalidate delayed/transient writes at the final Hue boundary**
  - owns Try It, ScreenSync wait/revalidate, Rust restore, native-scene acknowledgement;
  - target is one Hue-specific semantic final-write generation/lease;
  - recommended model: **Sol High**.

- **#324 — Away lighting: converge every light to off after partial Hue failures**
  - owns per-light hard-off acknowledgement, bounded retry/reconnect, lifecycle generation fencing;
  - recommended model: **Sol High**.

Do not create separate ScreenSync/Rust/Try-It issues unless #323 implementation proves they need independent release boundaries.

---

## 7. Remediation order

1. #322 sunrise and the Try-It portion of #323: clearest stale delayed writes.
2. #324 Away convergence: protects the strongest lifecycle/off state.
3. Complete #323 shared final-write authority and migrate ScreenSync, Rust, native scenes.
4. #246 manual ownership persistence if not already completed.
5. Effect partial-failure cleanup and dormant direct-write hardening only if still needed.

Security authentication work under #284 must remain separate from lighting ownership: a valid authenticated request is not permission to bypass DND, Away, Sleeping, manual, scene, ScreenSync, transit, fixture comfort, or external owners.

---

## 8. Model guidance after the audit

Use the project-wide economy policy:

- **Luna-class:** inventory, deterministic test additions after the contract is fixed, mechanical docs/status work.
- **Sol Medium:** ordinary bounded implementation/review where the ownership contract is already explicit.
- **Sol High:** #322/#323/#324 implementation and independent review because they involve delayed concurrency, lifecycle, ownership and physical-device correctness.
- **Astra:** not needed for implementation. Use only if a later architectural contradiction or independent high-end review materially justifies it.
- **Terra/legacy:** fallback only.

---

## 9. Audit integrity

- Audit was read-only.
- No HomeHub source, configuration, secrets, credentials, production data, services or devices were modified.
- No production/Latitude call or Hue write was performed.
- Astra completed extensive tracing but hit Codex usage exhaustion after 118,376 tokens before final synthesis.
- Sol independently re-opened and verified the material findings before they were accepted here.
- The audit runner recorded clean tracked/staged state before/after at the baseline SHA.
- Sandbox Git still reports the known `.pytest_cache/` permission warning; that cache is not part of the findings and was not modified.

Re-check current code and owning issues before implementation; this document is evidence, not a substitute for live/current authority.
