# Local LLM evidence gate — offline research fixture (#366)

> **Status:** Sandbox-only research candidate, NOT approved HomeHub Analyst/runtime.
> **Owner:** [#366](https://github.com/agatte/home-hub/issues/366). Background:
> [AI Semantic Layer](AI_SEMANTIC_LAYER.md); replay evidence
> [#240](https://github.com/agatte/home-hub/issues/240).
> The two fixtures are sanitized, reviewed examples, **not** a live incident feed.

## Why a typed fixture

In the first Qwen3-4B CPU trials, JSON syntax and evidence-ID membership passed
while a free-text claim declared Sandbox recovery unsuccessful even though its
own answer said the recovery outcome was unknown. An initial failure (I1)
cannot support a negative claim about a later recovery. Likewise, the success
of one VHDX mounting test (I2) does not prove all virtual-disk operations work.

No deterministic matcher can prove that *arbitrary natural-language sentences*
are entailed by cited evidence just because a citation string is present.
This deliberately narrow benchmark avoids that false assurance: the model can
only select **pre-reviewed fact IDs and the exact evidence IDs required for each
fact**, plus a fixed set of unresolved-question IDs. The validator rejects any
additional prose, unknown facts, incorrect citations, missing required facts,
contradictory statuses, missing abstentions, malformed/truncated JSON, ambiguous
duplicate keys, and oversized input. Only **deterministic, benchmark-owned text**
is rendered after a complete pass.

This is not a production semantic safety filter. The fixture author supplies the
ground truth; expanding to other incidents requires human review, evidence
provenance and a much larger independently held-out test set. A future Analyst
must not trust model-authored prose or device commands by default.

## Usage (offline, no model execution)

From the HomeHub repo root in an isolated Sandbox worktree, using the
already-installed Sandbox interpreter (no new dependency install):

```powershell
$py = 'C:\Work\home-hub-project\main\.venv\Scripts\python.exe'
& $py -B -m unittest discover -s tests -p test_eval_local_llm_grounding.py
& $py -B scripts/eval_local_llm_grounding.py `
  --case incident-withheld --response C:\example\answer.json
```

The single-test module does not depend on HomeHub backend service imports.
`--response` must be a **standalone JSON file**, NOT raw llama.cpp console output.
The checker reads at most 16 KiB of one regular file, makes no external calls,
writes no files, and returns 0 only for a complete match; failures return 1.

Accepted example for the deliberately **withheld-outcome** fixture:

```json
{
  "case": "incident-withheld",
  "facts": [
    {"id": "initial_failure", "evidence_ids": ["I1"]},
    {"id": "vhdx_test_passed", "evidence_ids": ["I2"]},
    {"id": "repair_proposed", "evidence_ids": ["I3"]}
  ],
  "unknowns": ["recovery_outcome", "root_cause"]
}
```

In the **complete** fixture, the reviewed I4 evidence supports
`recovery_confirmed`, I3 supports `repair_completed`, and I5 explicitly
documents that the root cause remains unknown. The complete fixture does *not*
include `recovery_outcome` in `unknowns`. Neither fixture allows a
`recovery_failed`, `root_cause_known` or `all_virtual_disks_work` assertion.

An earlier result containing `answer` plus arbitrary `claims[].text` will
be **rejected as incompatible**, even if it looks plausible; that deliberately
does not pretend to automatically detect semantic contradictions in prose.

## Acceptance boundaries

Initial CPU feasibility is proven on the operator's desktop; the first four
local responses had 3/4 valid JSON and the follow-up two had 2/2 parseable
responses but **failed semantic acceptance** due to unsupported recovery-failure
claims. Do not re-label that run as passing just because this narrow typed
validator passes its **synthetic offline tests**. The local model is not
integrated, GPU/offloading is deferred, and no real-host PowerShell execution
policy, driver, service, device or Obsidian Vault change is part of this work.
