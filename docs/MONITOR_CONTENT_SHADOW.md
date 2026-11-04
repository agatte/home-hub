# Issue #371: offline content brightness prototype

Draft [PR #479](https://github.com/agatte/home-hub/pull/479), 2026-11-04; no hardware acceptance or rollout. It does **not**
dim white pages. Existing resolve_target, Reconciler, manual backoff, Sleeping,
15% late-night ceiling and 5% production floor remain unchanged.

The unified supervisor injects one locked ContentSignal into ScreenSync and
monitor brightness. Standalone processes have no shared channel. The existing
2.5-second capture supplies a small whole-frame strided sample; only white share,
luma, media tri-state, timestamps and dwell survive. No screenshots, titles,
new routes or backend writes. Original ScreenSync payload fields remain intact.
The mailbox and aggregation use only the Python standard library, so optional NumPy
absence cannot prevent supervisor initialization or independent agent registration.
Four neutral-white samples spanning 7.5 seconds enter; three nonwhite samples
release. Media true/unknown resets immediately. Six-second expiry, capture gaps,
backwards clocks and wall/monotonic divergence discard dwell. Empty, malformed,
nonfinite/out-of-range pixels, nonfinite capture clocks and capture/processing
failures invalidate the mailbox immediately; recovery requires a fresh full dwell. Release affects
only diagnostics; no candidate can cause a physical brightness pop.

The pure policy proposes 2% / native 1 only for explicitly accepted Samsung VCP
maximum 50, display mapping and trustworthy nonmedia evidence, late_night and
non-Gaming/non-Sleeping. Otherwise it retains the caller's shipped target,
including manual-override abstention. Runtime reports manual ownership as unknown
rather than claiming reconciler override state; its proposal remains closed.
Runtime leaves mapping/media/native acceptance gates closed. Scalar-only INFO
observations report visual classification transitions at most once per 30 seconds
(coalescing transitions during that interval). Sustained white-like evidence in an
eligible mode/period reports a **visual hypothesis** of 2%, alongside the retained
production target and explicit false actuation authority. This hypothesis does
not establish display mapping, trustworthy nonmedia, native range or manual
ownership. It never reaches the writer.
Dark/gray/color content retains the existing curve rather than gaining a new
untested target.

Remaining gates: prove mss.monitors[1] maps to the selected physical VCP display;
verify native max 50 on that Samsung; strengthen/accept media qualification
(foreground false is not verified nonmedia: missing HWND, unrecognized browser
video, foreground on another monitor and background playback remain unresolved);
physically check readability at 1/50, video/game exclusion, transition comfort,
manual ownership and sleep/resume. Revalidate stale mode handling before any
future activation. Unknown mode provenance is not an activation authority.
No live capture, backend or hardware was exercised here. GitHub issue retrieval
was not attempted because this task prohibits network fetches; supplied issue
context is the basis. Publication and hardware changes require separate approval.

Publication history: draft PR #479 originally published at head 7718249,
with a tree matching local commit 46b7a214. The original head passed 113
focused local tests and GitHub CI run
[41798462730](https://github.com/agatte/home-hub/actions/runs/41798462730).
This review-remediation revision follows that original publication; its own
GitHub CI and physical acceptance must be verified separately.

Local remediation validation, 2026-11-04: the implementation worker reported
135 passing tests across its selected suites. An independent rerun of eight
explicit suites (content brightness shadow, monitor brightness, ScreenSync
agent backoff and picker, supervisor Windows setup, classifier, heartbeat and
resume recovery) passed **128 tests**. A separate independent agent-health
monitor suite passed **19 tests** (147 independently passing test cases in
these two runs; counts are not a single combined invocation). All used the
existing C:/Work/home-hub-project/main/.venv/Scripts/python.exe with
`-B -m pytest -q -p no:cacheprovider` in the isolated worktree. Independent
Ruff and `git diff --check` passed.
Regressions cover missing NumPy in a fresh interpreter with independent
registration, immediate invalidation and recovery, synthetic capture failures,
closed manual-unknown authority, scalar INFO transitions and rate limits.
Inspection confirms no shadow device calls and unchanged production reconciliation,
15% ceiling/5% floor, VCP readback/cooldown and ScreenSync HTTP payload.

Development worktree:
C:/Work/home-hub-project/worktrees/g50f-content-white-shadow-371-20261104.
No merge, deployment, live capture, service/task action or hardware write was
performed during development or review. Display/source/media/focus/native-range
and manual ownership, plus physical readability/transition/sleep acceptance,
remain activation blockers. Publishing this shadow-only revision does not authorize
its merger or installation on Windows; those remain separate review and rollout gates.
