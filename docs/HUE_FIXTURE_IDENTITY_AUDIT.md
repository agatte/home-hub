# Hue fixture identity audit — source-only prerequisite

**Scope:** #461 (real redesigned lighting acceptance), #284/#287 (caller
identity), #296 (Hue transport identity). This document is a *candidate*,
not an accepted mapping, operational report or permission to control lights.

## Why this gate exists

HomeHub's canonical fixtures are L1 living room, L2/L5 bedroom desk,
L3/L4 kitchen and L6 Plant Wash. `light_state_calculator.LIGHT_IDS`
currently maps them to Hue/v1 numeric IDs 1–6. The v1 bridge inventory
contains a `uniqueid` field, but HomeHub's ordinary `HueService.get_all_lights`
drops that field before returning UI/guard state. The draft guarded writer in
PR #530 checks the numeric ID and reachability. This prevents unknown *numbers*
but does not prove that Hue's numeric ID still denotes the same physical bulb
after re-pairing, bridge replacement or a stale bridge snapshot.

## Offline component

`backend.services.hue_fixture_identity.audit_hue_v1_fixture_bindings` is a
**pure, read-only structural comparator** between (a) separately accepted,
private operator-enrolled numeric-ID-to-stable-`uniqueid` bindings and (b)
the original raw Hue/v1 `get_api()` inventory object.

It accepts *untrusted data*, does no I/O, logs nothing, and returns only
approved L1–L6 numeric IDs with status strings. It never returns names,
`uniqueid` values or the raw inventory, automatically enrolls new IDs,
mints lighting authority, sends bridge commands or exposes a new endpoint.

| Status | Meaning |
| --- | --- |
| `matched` | Raw uniqueid exactly equals an enrolled value, structurally only |
| `unenrolled` | No operator-approved stable binding for this fixture |
| `invalid_enrollment` | Enrollment has illegal IDs, malformed or duplicated values |
| `inventory_unavailable` | Raw bridge inventory absent or not a mapping |
| `missing` | Expected v1 numeric ID absent from current inventory |
| `missing_uniqueid` | ID present but its reported stable identifier absent/invalid |
| `duplicate_uniqueid` | Same reported identifier appears on multiple bridge rows |
| `reindexed` | ID now reports another enrolled fixture's identifier |
| `mismatched` | ID reports a different, previously unapproved identifier |

A `matched` comparison is **not authorization**: a false/compromised
bridge, stale inventory, accidental local enrollment or spoofed caller can
still produce structural agreement. The function neither establishes
current bridge certificate identity nor records freshness or physical
control. There are no real enrolled IDs in the repository; test fixtures
are deliberately synthetic.

## Actual release gates — not satisfied by this PR

1. **Authenticated provenance:** establish a reviewed source for raw Hue/v1
   inventory, an authenticated Hue bridge identity and a freshness ceiling.
   Canonical #296 owns bridge TLS/identity; #287 owns caller identity/WS
   sessions. Read-only visibility does not imply permission to write bulbs.
2. **Operator enrollment:** on an approved real-host session, read the real
   bridge inventory only through the authorized typed/read-only interface.
   Verify each L1–L6 bulb physically and distinguish bedroom L2 vs L5 and
   kitchen L3 vs L4; capture the trusted mapping in an approved *private*
   store, never in Git, issues, PR comments, logs or frontend/WS state.
   Never auto-enroll new or changed IDs from Hue discovery.
3. **Mismatch test:** simulate ID swap, disappeared bulb, duplicate uniqueid
   and unknown new fixture; ensure a future integrated final-write guard
   denies such targets *before* any physical write, without bypassing
   ScreenSync/scene/transit/manual/host lifecycle authority.
4. **Integration only after review:** using the approved private bindings,
   gate both WS and REST manual writers (including bulk) at the existing
   final-write boundary with fresh identity and authoritative client checks.
   Code in this PR intentionally does **not** activate or wire such a gate.
5. **Operational validation:** separately authorize Latitude deploy and a
   reversible iPhone/kiosk, Hue app and fixture trial, collect observed
   before/after readings and actual ownership takeovers, then obtain owner
   acceptance of the original #461/#157 goal. Preserve `/classic` fallback.

**Current implementation status:** structural comparator + synthetic tests
only. **Current production state:** unchanged and not verified here.
Neither this document nor any passing offline test is physical identity
verification or security approval.
