# Navigation-v1 isolated runner contract

Slice 6 separates two different claims:

1. **Closed-root evidence:** the in-process navigation-v1 composition root has a
   reviewed, exact project import closure; all light/event side effects terminate
   in in-memory recording sinks; runtime tripwire tests fail on socket,
   subprocess, dynamic-import, SQLite, shell, or arbitrary file-open attempts.
2. **Operational isolation:** running an arbitrary replay bundle as a supported
   operator workflow must additionally be contained by an OS/container boundary.
   Python monkeypatches and import tests are evidence, not that boundary.

A supported operational runner must establish all of these conditions **before**
the child replay process starts:

- no network access;
- no physical device access;
- no subprocess, shell, or exec capability;
- immutable replay code and immutable bounded input;
- no production filesystem, Home directory, `.env`, credentials, databases, or
  service state;
- no writable host output path while the replay child runs; bounded output is
  exported only after guest completion is positively proven.

The launcher must fail closed if any guarantee cannot be established. It must not
fall back to an ordinary Python process or accept a caller-supplied adapter,
factory, service object, plugin, executable configuration, pickle, or other
active object.

## Current status

**Operational isolation accepted on Windows 11 - 2026-10-02.** The reviewed
backend now runs navigation-v1 through a fresh transient Windows Sandbox and a
broker-created zero-capability AppContainer child. The Sandbox starts with
networking, audio/video input, printer, clipboard, and vGPU disabled and exposes
only the immutable replay stage as a read-only mapping. It does not mount the
Home Hub checkout, Home directory, `.env`, credentials, production databases,
Host Bridge paths, or device/service state into the replay Sandbox.

The trusted guest broker is launched explicitly with `wsb exec -r System`
after Sandbox startup; the implementation does not rely on WSB
`LogonCommand` or guest process exit-code propagation. The broker copies and
verifies the staged closure inside the guest, creates a zero-capability
AppContainer profile, denies that child access to the guest control-plane state,
and runs the replay child with the reviewed process/handle/Win32k restrictions.
No writable host mapping exists while that child is running.

After the broker has written guest-local `status.json` and `done.marker`,
the host positively proves guest readiness through the calibrated WSB exec
timing channel. Only then does the host add a fresh writable export mapping,
perform a host-visible share handshake, export the bounded result, verify the
isolation self-test, stop the exact Sandbox ID, and clean only the exact replay
temp roots after a proven successful stop. Ambiguous start/stop outcomes fail
closed and preserve evidence.

The controlled real-host acceptance E2E on 2026-10-02 passed:
`1 passed, 44 deselected in 31.57s`, pytest exit `0`, with post-test
`wsb list --raw` exit `0` and no remaining Sandbox record. The same accepted
replay implementation remained byte-unchanged after merging current `master`;
focused validation was `44 passed, 1 skipped` and the broader replay suite was
`90 passed, 1 skipped`.

The first evidence-backed navigation fixture remains separately
`EVIDENCE_GATED`; no historical acknowledgement timing or human/environment
counterfactual is invented by this runner contract.

## Deterministic trace result

The Slice 7 replay result adds `trace_jsonl` and `trace_record_count` without
changing the isolation boundary. `trace_jsonl` is a canonical, deterministic
JSONL semantic trace produced entirely inside the closed replay root. The
reviewed project closure explicitly includes `backend/replay/trace.py`; no new
live adapter, filesystem, process, network, or production-state dependency is
introduced.

Trace records distinguish `FACT`, `DERIVED_DECISION`, `PROPOSAL`,
`SUPPRESSION`, `REQUEST`, and `SIMULATED_RESULT`. Gate states are explicit:
`passed`, `blocked`, `not_evaluated`, or `unknown`. In particular, the current
Transit path records the missing physical-authority gate as `not_evaluated`;
it is not silently treated as passed.

Synthetic fixtures are labeled with `certainty="synthetic_contract"`. They may
prove deterministic replay contracts such as dwell, timeout, no-refire,
suppression, and fake acknowledgement/cache behavior, but they are not
historical evidence. The first real historical fixture remains
`EVIDENCE_GATED`.
Non-synthetic runs use `certainty="current_code_interpretation"`; they are not labeled as historical reproduction.
