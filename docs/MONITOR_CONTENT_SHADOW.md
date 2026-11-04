# Issue #371: offline content brightness prototype

Local prototype, 2026-11-04; no hardware acceptance or rollout. It does **not**
dim white pages. Existing resolve_target, Reconciler, manual backoff, Sleeping,
15% late-night ceiling and 5% production floor remain unchanged.

The unified supervisor injects one locked ContentSignal into ScreenSync and
monitor brightness. Standalone processes have no shared channel. The existing
2.5-second capture supplies a small whole-frame strided sample; only white share,
luma, media tri-state, timestamps and dwell survive. No screenshots, titles,
new routes or backend writes. Original ScreenSync payload fields remain intact.
Four neutral-white samples spanning 7.5 seconds enter; three nonwhite samples
release. Media true/unknown resets immediately. Six-second expiry, capture gaps,
backwards clocks and wall/monotonic divergence discard dwell. Release affects
only diagnostics; no candidate can cause a physical brightness pop.

The pure policy proposes 2% / native 1 only for explicitly accepted Samsung VCP
maximum 50, display mapping and trustworthy nonmedia evidence, late_night and
non-Gaming/non-Sleeping. Otherwise it retains the caller's shipped target,
including manual-override abstention. Runtime leaves all acceptance gates closed
and logs diagnostic proposals at DEBUG; it never passes them to the writer.
Dark/gray/color content retains the existing curve rather than gaining a new
untested target.

Remaining gates: prove mss.monitors[1] maps to the selected physical VCP display;
verify native max 50 on that Samsung; strengthen/accept media qualification
(existing foreground heuristics can miss browser video/background playback);
physically check readability at 1/50, video/game exclusion, transition comfort,
manual ownership and sleep/resume. Revalidate stale mode handling before any
future activation. Unknown mode provenance is not an activation authority.
No live capture, backend or hardware was exercised here. GitHub issue retrieval
was not attempted because this task prohibits network fetches; supplied issue
context is the basis. Publication and hardware changes require separate approval.

Offline validation: 102 tests passed using the existing main worktree venv,
`python.exe -B -m pytest -p no:cacheprovider`, covering the new synthetic module
plus monitor brightness, ScreenSync backoff/picker, supervisor Windows setup,
heartbeat and resume recovery. Ruff passed on all five touched Python files;
`git diff --check` passed. New synthetic cases cover accents/text, gray/dark,
bright chroma, media true/unknown, flash/dwell/release/recovery, clock gaps and
divergence, delayed processing, manual policy abstention, native mapping and
unchanged payload fields. Existing Reconciler/manual-backoff tests also passed.
All evidence is local and uncommitted in the named task worktree; no GitHub
publication, live capture, network fetch, service action or hardware write.
