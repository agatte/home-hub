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
