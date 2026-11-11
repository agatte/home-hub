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
