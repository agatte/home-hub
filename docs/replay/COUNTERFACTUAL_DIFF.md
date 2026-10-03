# Navigation-v1 fixed-evidence counterfactual diff

This document is the operator/developer handoff for the bounded replay diff implemented in
`backend/replay/diff.py`.

The diff is intentionally narrow. It compares two deterministic navigation-v1 semantic traces
under one declared immutable evidence bundle and one declared recording-adapter response policy.
It does **not** infer how a person, room, camera, Hue bridge, or other environment would have
responded to a different physical action.

## Preconditions

Use the diff only when both runs:

- consume the same validated bounded fixture;
- use the same captured evaluation opportunities and initial checkpoint;
- use the same fake/recorded adapter response policy for requests that match;
- preserve the same trace certainty class;
- run through the reviewed offline replay boundary.

The implementation additionally compares the trace `FACT` streams and refuses a fixed-evidence
comparison when those captured facts differ.
## API

```python
from backend.replay.diff import (
    compare_fixed_evidence_traces,
    render_trace_diff_markdown,
)

result = compare_fixed_evidence_traces(
    baseline_result["trace_jsonl"],
    candidate_result["trace_jsonl"],
    evidence_identity="bundle-manifest-sha256:<digest>",
    response_policy_identity="adapter-policy-sha256:<digest>",
    baseline_label="baseline",
    candidate_label="candidate",
)

markdown = render_trace_diff_markdown(result)
```

The identity strings are explicit audit inputs. They should be derived from the exact fixture
manifest and the exact adapter-result policy used for both isolated runs; do not use a human label
such as "same capture" in place of a stable identity.
## Alignment and output

Records are not aligned by `record_id` or raw trace row number. The diff aligns by:

- causal dispatch identity, or a stable cause/evidence anchor when no dispatch sequence exists;
- participant and trace kind;
- semantic action/input kind when available;
- owner and affected light IDs;
- deterministic occurrence number for repeated equivalent anchors.

The result reports changed, inserted, deleted, and unchanged semantic records. Changed records
surface differences in virtual time, causes/evidence, state digest/delta, decision, reason codes,
gates, owner, lights, payload, and simulated result. Request IDs are retained for explanation but
are not treated as the causal alignment key.

`render_trace_diff_markdown()` provides a deterministic human-readable rendering of the same
structured result.
## Certainty and claims

The current trace contract supports:

- `synthetic_contract` — useful for proving replay mechanics and regression contracts;
- `current_code_interpretation` — captured facts interpreted by the supported current replay
  profile.

The fixed-evidence diff refuses to mix certainty classes. A synthetic comparison is never
historical evidence.

Historical reproduction remains available only when the original evidence, implementation,
configuration, dependencies, and acknowledgement semantics are sufficiently known. The July 2026
incident does not currently meet that standard.

## Real-fixture gate

No eligible real navigation-v1 fixture had been captured when this handoff was written.

The first honest fixture should be a naturally occurring daytime Home + Working interval, with
desktop sensing unavailable, one backend boot, no active scene/effect/ScreenSync owner, and a
quiescent initial cut. Prefer a bounded interval that includes strong presence, absence, one
navigation activation, timeout/cooldown, and continued absence.
Capture is opt-in through `NavigationIncidentCapture.arm_runtime()`; it is not enabled by normal
bootstrap. The recorder defaults to 15 minutes / 16 MiB, records explicit gaps instead of silently
overwriting, and exports only:

- `manifest.json`
- `initial.json`
- `inputs.jsonl`
- `expected.json`

After an eligible capture exists, run the same fixture through the baseline and candidate isolated
artifacts, then compare their `trace_jsonl` values with the API above. Evidence-backed golden
assertions may be added only after that capture validates successfully.

Until then, #240 is **IMPLEMENTATION COMPLETE / REAL-FIXTURE EVIDENCE_GATED**. The remaining gate is
evidence acquisition, not another replay architecture or implementation slice.
