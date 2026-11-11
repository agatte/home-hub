# #131 offline action-feedback shadow (2026-11-11)

Source-only prototype originally developed against `master`
`cd9e8fff485fe68a40b59a1f2719e28e359858da` on branch
`work/131-autonomy-feedback-shadow-20261111`. GitHub PR/commit history is the
authority for integration status. This module is not deployed, connected to the
runtime, or permitted to actuate. The controller checked issue #131 (open on
2026-11-11) and the source baseline; production health is unverified. No
personal history was accessed.

## Existing evidence and target

| Local source evidence | What it actually establishes |
| --- | --- |
| `backend/services/ml/lighting_learner.py`: `get_overlay`, `recalculate`, `write_learned_pref`, `scan_for_suggestions` | Existing EMA learner supplies an **active overlay**, learns manual trigger buckets, collapses drag clusters, and produces suggestions. Acceptance can persist a learned brightness. Left untouched. |
| `backend/services/event_logger.py`: `log_light_adjustment` | Records before/after values, trigger, mode, weather and zone/posture enrichment. Does not guarantee originating automatic decision, policy, session, actor or verified correction linkage. Adjacency cannot establish dissatisfaction. |
| `backend/services/light_override_manager.py` | Owns manual stamps and transit protection/application lifecycle. Its writes and ownership remain outside this prototype. |
| `backend/services/ml/music_bandit.py`: `retrain`; `music_learning_provenance.py` | Session-scoped owned playback outcomes, dedupe and neutral treatment of unscoped rows are useful precedents, not reusable lighting scores or DB authority. |
| `backend/services/music_feedback.py`: `record` | Explicit provider-qualified judgments with idempotency/conflicting-ID handling; separate from playback and bandit rewards. |
| `backend/services/lighting_comfort_shadow.py` | Pure supplied-snapshot technical audit; authored brightness comparisons do not establish subjective comfort or permission. |
| `tests/test_lighting_learner.py` | Existing synthetic EMA, bucket, suggestion and drag-collapse contracts, not real per-action outcomes. |

[PROJECT_SPEC](PROJECT_SPEC.md#autonomy-trust-and-interaction) describes per-action
trust, corrections and demotion as a target. [EXECUTION_MAP](EXECUTION_MAP.md)
#131 requires independent outcome provenance; mode/fusion agreement is not user
feedback. This prototype chooses a narrower review-only assessment, with no
graduation ladder or runtime connection.

## Qualified outcome contract

`assess` takes frozen typed claims, an explicit evaluation epoch second, and an
independent expected-event map. Exact equality binds **every field** of both the
originating decision and feedback, including action, light, mode, period, zone,
policy, decision and session. Missing/mismatched links never count a manual
adjustment as policy dissatisfaction. Event claims cannot certify themselves.

Only the fictional brightness/L2 (`"2"`)/working/evening/desk context is supported.
Decision/session/policy identity is mandatory (a deliberate narrowing). Qualified
claims require Home, sole automation ownership at decision time, no temporary
context or experiment, context age <=60 seconds, context confidence in [0.9,1],
and an explicit fictional owner UI response within 600 seconds with source age
<=30 seconds. These are experimental screening thresholds, not calibrated
probabilities, subjective preferences, safety levels or autonomy thresholds.
Owner conflicts including manual, scene, ScreenSync, transit and unknown, and
non-Home states abstain. Omitted owner/house fields default to unknown and never
silently qualify an event as Home/automation. Manual *correction after* the
decision is a distinct explicit outcome; existing manual ownership of the
originating decision blocks.

Acceptance must affirm the exact decision brightness. A correction must explicitly
target that decision and change brightness by >=5 Hue units. Arbitrary slider
use, silence and detector agreement contribute no positive or negative outcome.
Invalid/future/naive-style/non-integer timestamps abstain; epochs use UTC for day
diversity. Only the last 30 days of supplied events participate. This is an
in-memory evaluation window, **not a retention change**.

Exact duplicate events collapse; conflicting IDs abstain independent of order.
Latest settled feedback per session supplies at most one sample, so slider drags,
decision replays and multiple decisions within one session cannot inflate sample
or day diversity. Conflicting accept/correct kinds abstain; materially different
corrections separated by more than three seconds also block as unstable. Five sessions on at
least three UTC days and a final-value spread <=10 are needed for a median
technical candidate. Numeric bounds [1,254] mean valid Hue brightness only;
every candidate still requires final owner and safety validation.

Any qualified rejection or quick explicit reversal vetoes the entire window,
even after prior positive evidence. It cannot be outweighed by passive evidence.
This conservative temporal hysteresis persists until the negative ages out;
recovery also needs sufficient unexpired positive evidence. In-scope ambiguity
withholds a candidate rather than silently restoring one. Results expose stable
sorted reasons/counters and only `abstain` or `human_review_suggestion`.

## Fictional before/after and limits

Run `python -B scripts/demo_action_feedback_shadow.py` using the existing Sandbox
venv. It writes deterministic JSON to stdout only:

| Case | Independent sessions/days | Result |
| --- | --- | --- |
| Before | 2/2 | Abstain: insufficient evidence |
| After five linked fictional corrections from 180 toward 140–142 | 5/5 | Human review brightness candidate 141 |
| Add one unlinked slider claim | 5/5 | Abstain: missing independent link |
| Add one explicit quick reversal | 5/5 | Abstain: negative-feedback window veto |

All results permanently say `unverified_offline_claims`, even if supplied claims
exactly match the oracle. The demo constructs its own synthetic oracle; this
illustrates computation, **not independent real-world verification**. Tests use
separately constructed literal expectations and adversarial mutations. A caller
can fabricate both maps: Python dataclasses and equality are not authentication.
No production provenance adapter, outcome capture, current-owner validation,
completeness assurance or UI delivery exists. A caller omitting negatives cannot
be detected here. Arbitrarily segmented/fabricated sessions are not real evidence.

Zero runtime authority: no live imports, devices, account/DB/network access,
persistence, retention changes, actuation permission field, automation registration,
house-state changes or active learner changes. Rollback requires dropping only
these four source files during controller integration; no runtime state to undo.

## Verification and next gate

Focused tests cover independent-link tampering, source/actor age, identities,
duplicates/drags/replays, invalid timestamps/range/confidence, sparse sessions/days,
ownership/house-state exclusions, temporary experiments, noise/conflicts,
negative demotion/window hysteresis, policy isolation and no permission interface.
Checks use the existing `C:/Work/home-hub-project/main/.venv/Scripts/python.exe`
with `-B`; pytest cache and bytecode writes are disabled. Full commands and final
counts accompany the worker handoff. Verified locally after the controller's
fail-closed default regression: **68 passed**, scoped Ruff passed, all three Python sources compiled in memory without writing bytecode,
and two demo subprocess runs emitted identical **1882 bytes** on Windows.
`git diff --check` plus new-file `git diff --no-index --check -- NUL <path>`
checked all four paths (the latter returns 1 for a new-file difference; no
whitespace diagnostics). No existing runtime tests need broadening
because no existing source or contract changed.

```powershell
& C:/Work/home-hub-project/main/.venv/Scripts/python.exe -B -m pytest tests/test_action_feedback_shadow.py -q -p no:cacheprovider --disable-warnings
& C:/Work/home-hub-project/main/.venv/Scripts/python.exe -B -m ruff check --no-cache backend/services/ml/action_feedback_shadow.py scripts/demo_action_feedback_shadow.py tests/test_action_feedback_shadow.py
& C:/Work/home-hub-project/main/.venv/Scripts/python.exe -B scripts/demo_action_feedback_shadow.py
git diff --check
```

Next exact real-world gate: owner-approved design/review of an independently
verified decision-to-explicit-response capture contract, including source/actor
authentication, authoritative ownership/context snapshots, stable policy/session
IDs, freshness, replay protection, completeness/negative capture and cancellation.
Then separately authorize a bounded sanitized collection/evaluation plan. Existing
LightAdjustment history alone cannot satisfy this gate. Controller independently
reviews and integrates; no commit/push/PR/merge, live collection, migration,
deployment, device write or new automation permission is authorized here.

## Second milestone: fictional producer receipt join (2026-11-11)

This source-only extension follows the first milestone merged in PR #524
(controller-supplied baseline `a41f7102e93827c067db85722d4896654d94d6e6`).
The first-milestone text above remains its historical contract. This worker used
local source/docs only; no fresh GitHub status, production or personal history
was read. Issue #131 remains the owning workstream; publication/integration and
independent exact-head CI belong to the controller.

`backend/services/ml/action_feedback_receipts_shadow.py` adds frozen stdlib
receipt types and `evaluate()`, with no runtime, storage, device or network
imports. It reuses `Context`, `Decision`, `Feedback`, `ExpectedLink`, `Assessment`
and `assess()` unchanged. Four independent fictional producer streams describe:

- Decision intent, including exact action/context/policy/session and brightness.
- Final writer ACK, including its own exact intent copy and owner snapshot ID.
  `acknowledged=True` illustrates an accepted final outbound write, not measured
  physical brightness. An intent acceptance alone is insufficient: current
  `LightingAcceptanceReceipt` explicitly is not a transport acknowledgement;
  Hue v2 `_write_acknowledged` separately checks the resource/error envelope.
- Authoritative owner/context interval covering decision through response.
  This single interval is a deliberately conservative continuous-history claim,
  captured at/after its end, with a separate Home/automation assertion and fresh
  context timestamp at both endpoints. A second snapshot for the same decision,
  including takeover/ABA, blocks rather than replacing the first.
- Explicit UI response, including stable event ID, exact response contents,
  ACK/owner IDs, independent owner-qualification claim and interaction type.
  Submitted feedback must equal this independently supplied UI record in every
  field. A raw slider, scene selection, silence or source string cannot qualify.

The expected map is projected from corroborated producer receipts, never from
submitted feedback. Exact decision equality binds final brightness and all intent
fields; UI response equality separately binds the requested correction brightness.
The explicit correction is feedback only: this module never applies it or grants
permission to apply it. Manual ownership before the response blocks qualification.
All supplied rows belong to one narrowly scoped batch. Mixed contexts/policies,
missing/unreferenced receipts, duplicate IDs (even identical replays), duplicate
final writes, wrong sessions, ambiguous owner timelines and suspicious extra rows
block the whole batch. There is no salvage of five positives after dropping an
uncertain sixth row. Missing/failed/unobserved ACKs cannot count.

Each of decision/apply/owner/UI must supply exactly one complete, continuous
coverage claim spanning the **entire existing 30-day assessor window through
explicit `now`**, including quiet intervals. Ordered receipt manifests must match
all supplied producer receipts exactly, with sequences 1..N, unique receipt IDs
across streams and nondecreasing source/capture timestamps. Receipt arrival order
is irrelevant. Missing/gapped/torn coverage blocks. Capture lag is at most 30
seconds (owner interval lag is measured from its end); clocks cannot be future,
non-integer or inconsistent with causal ordering. Decision/context/response
freshness and scope checks, five-session/three-day evidence, variability screening
and negative-window hysteresis remain owned by the original assessor. The
two endpoint context checks require independently fresh observations at the
originating decision (within 60 seconds) and explicit response (within 30
seconds), so an old owner observation cannot qualify later feedback. The
continuous-owner interval remains a synthetic claim, not authenticated history
or a calibrated autonomy policy.

**Threat model:** every stream, coverage manifest, source name, qualification flag
and interval is still an unverified caller-supplied claim. A malicious source can
forge all streams or hide a negative while fabricating complete coverage. These
fixtures neither authenticate a person nor demonstrate real owner approval.
Sequence/manifest checks detect inconsistencies in supplied evidence, not omitted
real-world history. Every result always says `unverified_offline_claims`, including
`human_review_suggestion`. No verified/provenance/actuation permission status is
introduced. Real credential validation and trusted producer boundaries are absent.

`python -B scripts/demo_action_feedback_receipts_shadow.py` emits fully fictional,
deterministic before/after JSON to stdout: two linked responses abstain; five
receipt-linked corrections on five dates yield at most a human-review candidate;
missing final ACK, partial coverage or explicit reversal abstains. No files,
database, host, Hue, real history or network are accessed by the demo beyond
ordinary Python source imports. The tests separately exercise forged fields,
coverage, replay, ownership, freshness, negative veto and input permutations.

Still unimplemented and separately gated: real decision/final-ACK capture at the
existing write chokepoint, independently authenticated UI delivery and actor
qualification, authoritative continuous owner/context history and cancellation,
restart-safe producer/session identities, trustworthy clock/sequence boundaries,
complete negative/reversal capture, privacy/retention decisions, and a bounded
sanitized evaluation plan. Existing `log_light_adjustment` cannot supply these
joins. Music provenance is a precedent only; the active lighting learner and all
runtime write paths remain untouched. No adapter, API auth, migration, durable
history, config, live polling, transition or actuator policy is added here.

Local verification commands (existing Sandbox venv, no downloads):

```powershell
& C:/Work/home-hub-project/main/.venv/Scripts/python.exe -B -m pytest tests/test_action_feedback_receipts_shadow.py tests/test_action_feedback_shadow.py -q -p no:cacheprovider --disable-warnings
& C:/Work/home-hub-project/main/.venv/Scripts/python.exe -B -m ruff check --no-cache backend/services/ml/action_feedback_receipts_shadow.py scripts/demo_action_feedback_receipts_shadow.py tests/test_action_feedback_receipts_shadow.py
& C:/Work/home-hub-project/main/.venv/Scripts/python.exe -B scripts/demo_action_feedback_receipts_shadow.py
git diff --check
git diff --cached --check
```

The handoff reports final test counts, two-run demo identity and explicit
new-file whitespace checks. Only the four second-milestone paths are changed;
no worker commit/push/PR/merge/deployment or live action is authorized.

Second-milestone local result: **186 passed** (118 receipt cases plus the original
68), scoped Ruff passed, and two independent demo subprocesses emitted identical
**2008 bytes**, SHA-256
`08ecbb20e86c9ee5b5dd098f2776e9942da4a12afddc01f674646912de1ef41a`.
Tracked/staged diff checks and all three untracked-source whitespace checks
reported no whitespace errors (new-file `--no-index` checks return 1 for the
file difference itself). No integration or real-world acceptance is implied.

## Phase 3: dormant bounded capture seam (2026-11-11)

**SOURCE-ONLY, OFF by default, never runtime-registered.** This milestone uses
owner-specified base `88e7575a76bb5aee81c501004d16aa58c6bf63fd` in the isolated
`action-feedback-capture-seam-131-20261111` worktree. Only the new capture module,
its tests/demo and this document change. No fresh GitHub/network evidence was
requested: the task prohibits network fetches. Integration status beyond the
supplied base and production health remain unverified. No real household data,
consent, authentication, collection or preference application was implemented.

### Contract and invariants

`lighting_feedback_capture_seam.py` reuses the Phase 2 frozen receipt contracts
and evaluator. `CaptureSession()` retains nothing and rejects every producer.
There is no runtime enable switch. `synthetic_for_tests()` is the sole opening
factory: its caller-supplied flags represent fictional test claims, **never a
real grant**. Preflight requires explicit consent, fictional principal, exact
brightness/L2/working/evening/desk/policy scope, a nonempty allowed-verb subset,
integer start/expiry (exclusive expiry, at most seven days), and no historical
backfill. Each session has a distinct process-local object identity; a new
session rejects old ports. Nothing survives a process restart.

Separate methods accept decision emission, final-write ACK, owner/context
interval evidence, and explicit UI producer receipt plus separate submitted
payload. `SyntheticPort` is a separate trusted-side **fixture** argument, with
producer/session identity and strict verification flags. UI additionally needs
an explicit actor-qualified principal from that port; payload source/actor strings
cannot supply it. No method derives producer evidence from submitted feedback.
The demo creates UI-producer and submission objects separately. Equality is
checked before the submitted payload is retained; Phase 2 alone builds the
expected-link map from producer evidence during explicit offline evaluation.

The sequential, single-thread API preserves each producer's arrival sequence;
it never sorts, drops bad records or repairs gaps. Global capture time cannot
reverse; producer timestamps cannot reverse; source capture lag is at most 30
seconds; sequence numbers must be contiguous from 1. Source and capture timestamps
must be within the consent interval, with no backfill before its start. Decision
and session identities cannot replay. Scope, values, decision freshness and
Home/automation context are screened before retention. Final writer intent must
exactly match the decision and ACK must be exactly `True`; skipped, partial,
deduplicated or failed writes are not ACKs. Owner intervals must cover the
response endpoint with fresh context at decision and response. The same explicit
owner revision is required at decision, ACK, owner interval and UI; conflicts or
ABA must cancel the session rather than be hidden behind a repeated revision.
Manual, transit, scene, ScreenSync, unknown ownership and Away/Sleeping context
cannot qualify. Phase 2 revalidates the complete joined batch at evaluation.

Every failed/malformed/duplicate/conflicting record destroys the entire batch and
closes the session. Explicit `cancel()` handles a capture gap, takeover or restart;
`clear()` and `revoke()` are also terminal and empty all retained rows/identity
indexes. Retention is capped at 100 producer records (default 80); overflow
invalidates rather than evicting negatives. UI submissions are capped one per UI
record. Known string identities and policy IDs are capped at 80 characters.
Timestamps are explicit caller inputs: there is no clock or expiry daemon. Every
record and seal checks expiry; the caller must clear/revoke or discard an idle
session to release memory. No claim of automatic wall-clock deletion is made.

`seal(now=...)` requires a nonempty complete four-stream batch, returns frozen
tuples, closes and clears the session, and **never invokes evaluation**.
`OfflineBundle.evaluate_offline()` normally abstains with `coverage_unknown`:
a short session cannot establish the assessor's 30-day coverage, quiet periods
or absence of omitted negatives. Only explicitly named
`synthetic_full_window_coverage=True` fabricates coverage for a test demonstration.
It cannot prove real completeness. Five fictional decisions in distinct sessions
on five days yield at most `human_review_suggestion` (140 in the demo).
All results remain `unverified_offline_claims`. Reversal still vetoes the window.
There is no apply callback, automatic evaluation, persistence or IO interface.

### Threat model and realistic next integration design

These dataclasses and Python object identities are consistency checks, not a
security boundary. A caller can fabricate ports, verification flags, owner
revisions, timestamps, all producer evidence and coverage. An omitted real
negative or unreported takeover cannot be discovered by a pure module. Exported
immutable bundles are detached fixture copies; revoking a session cannot erase
copies already held by a caller. Real authentication remains unimplemented.

A separately reviewed real design must establish the principal on the server,
never from client JSON, and bind producer credentials/capabilities to independent
writer, authority and UI boundaries. It must obtain exact intent and **successful
L2 transport ACK** at the final write chokepoint, revalidate final writer ownership
and context, and retain cancellation/revision evidence through the explicit UI
response. Current source inspection confirms `LightingAcceptanceReceipt` is an
outbound acceptance, not a transport ACK; `LightApplicator` separates successful,
failed, skipped and deduplicated IDs. Its existing navigation incident hook is
not a feedback adapter. `LightingAuthority` semantic/owner revision invalidation
is relevant design evidence, not a real capture grant. `LightOverrideManager`
manual/transit protection and EventLogger adjustment enrichment do not establish
an authenticated action-feedback join. No changes to these interfaces were made.

Future consent/retention UI must explain this exact light/context, verbs, finite
expiry, memory/export limits, revoke/reset semantics and no historical backfill.
Restart, cancel, disconnect, sequence gap, overflow and ownership takeover must
invalidate collection, including ABA and missed intervals. A real source design
must prove negative/reversal and quiet-period completeness over the entire
assessment window or abstain; successful joins cannot substitute for coverage.
The active LightingPreferenceLearner remains separate and unchanged.

**Next authorization gate:** controller independently reviews these four paths
and reruns local checks before deciding integration. A future real capture design,
source authentication, consent UI, retention/export policy and bounded sanitized
collection plan require separate explicit owner authorization. No runtime adapter,
registration, live capture, production release or physical-system authority is
included. The worker performed no commit, push, PR, merge or deployment.

### Phase 3 local validation

Using the existing Sandbox venv, with `-B`, no pytest cache and no downloads:

```powershell
& C:/Work/home-hub-project/main/.venv/Scripts/python.exe -B -m pytest tests/test_lighting_feedback_capture_seam.py tests/test_action_feedback_receipts_shadow.py tests/test_action_feedback_shadow.py -q -p no:cacheprovider --disable-warnings
& C:/Work/home-hub-project/main/.venv/Scripts/python.exe -B -m ruff check --no-cache backend/services/ml/lighting_feedback_capture_seam.py scripts/demo_lighting_feedback_capture_seam.py tests/test_lighting_feedback_capture_seam.py
& C:/Work/home-hub-project/main/.venv/Scripts/python.exe -B scripts/demo_lighting_feedback_capture_seam.py
git diff --check
git diff --cached --check
```

Final focused result: **284 passed** (98 capture cases plus 186 prior milestone
cases), **5.85 seconds**; no warning summary was emitted. Scoped Ruff passed.
Two independent no-argument demo subprocesses emitted identical **888 bytes**,
SHA-256 `9dffc6c1e7ba357dacce3127218d6affe410a3c459a0be79003655c37e824c4d`.
The demo reports inactive/default zero retention, gap cancellation, unknown
coverage abstention and explicitly fabricated review-only evidence. Staged and
unstaged whitespace checks plus individual new-file `--no-index --check` checks
passed (exit 1 from each new-file difference is expected, with no diagnostics).
These are synthetic local contracts only; no runtime/physical acceptance is
claimed. No tools were installed and no existing runtime source was edited.

Git emitted only line-ending normalization warnings: docs/tests LF to CRLF and
demo CRLF to LF on a future Git touch. No whitespace errors were reported.

Controller review (2026-11-11): the bundle's evidence label is now a fixed
read-only property, not a constructor field; even a synthetic caller cannot
label the exported bundle as verified. A regression test rejects attempts
to replace it with a forged status. These remain source-only consistency tests,
not real actor/source verification. Final test count and Git integration are
recorded on issue #131.
