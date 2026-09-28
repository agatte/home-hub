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
- output only through a preopened result stream owned by the launcher.

The launcher must fail closed if any guarantee cannot be established. It must not
fall back to an ordinary Python process or accept a caller-supplied adapter,
factory, service object, plugin, executable configuration, pickle, or other
active object.

## Current status

The repository does not currently contain a reviewed launcher that can enforce
all of the requirements above. Therefore
`backend.replay.isolated_runner.require_supported_isolation()` and
`run_navigation_v1_isolated()` intentionally refuse operational execution.

This does **not** block unit/contract testing of the closed root with synthetic
validated bundles. It does block describing those in-process tests as the
production no-actuation sandbox and blocks an operator-facing replay command
until a real isolation backend is accepted.

The first evidence-backed navigation fixture remains separately
`EVIDENCE_GATED`; no historical acknowledgement timing or human/environment
counterfactual is invented by this runner contract.
