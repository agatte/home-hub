# Local LLM #366 independent holdout — offline candidate

> **Status:** Sandbox research candidate, not a HomeHub feature or model rollout.
> **Owner:** [#366](https://github.com/agatte/home-hub/issues/366);
> predecessor [PR #379](https://github.com/agatte/home-hub/pull/379).
> **Safety:** no network, inference, service or device control in this evaluator.

## What changed from the merged two-case fixture

The earlier fixture established an important limit: cited JSON with real evidence
IDs can still contain false conclusions. Its deterministic allowlist rejects that
specific failure but does not measure incremental local AI value. This follow-up
sets out **10 cases, 30 separately graded propositions, and four verdict classes**:
supported (9), contradicted (7), unknown (12), conflicted (2).

Five case pairs/contrasts cover: Windows Sandbox recovery vs withheld outcome;
Obsidian read-only preview vs hidden CI/merge proof; manual Sonos policy merge vs
missing deployment/physical acceptance; 04:30 backup vs unproven causal attribution;
and PC wake/physical-room authority plus contradictory qualified sensors. A further
merge-vs-deployment example uses #379. Evidence is **sanitized and condensed** from
the cited issues/PRs or explicitly synthetic; fixture prose is not a live evidence
feed. Source-inspired cases include references; source fidelity needs independent
review before benchmark scores are considered decisive.

| File | Purpose |
| --- | --- |
| `tests/fixtures/local_llm_holdout_366.json` | Reviewed gold; never send to model |
| `scripts/local_llm_holdout_366.py` | Export *ungolded* prompts; score normalized JSON |
| `tests/test_local_llm_holdout_366.py` | No-model negative controls and scoring tests |

## Offline usage inside the existing isolated Sandbox worktree

```powershell
$py = 'C:\Work\home-hub-project\main\.venv\Scripts\python.exe'
& $py -B -m unittest discover -s tests -p test_local_llm_holdout_366.py -v

# Use a new unique destination under the Sandbox TEMP directory:
$promptDir = Join-Path $env:TEMP ('hh-366-prompts-' + [guid]::NewGuid().ToString('N'))
& $py -B scripts/local_llm_holdout_366.py --export-prompts $promptDir

# After separately approved inference, score normalized standalone JSON:
$responseDir = Join-Path $env:TEMP 'hh-366-responses-operator-created'
& $py -B scripts/local_llm_holdout_366.py --score-responses $responseDir
```

The export refuses an existing destination rather than overwriting anything.
**Do not feed the original fixture JSON to the model.** It contains the answers.
Case IDs are neutral and do not disclose withheld outcomes.
Published gold is not a secret; this is not an unseen benchmark.
Only individual exported `*.prompt.txt` files may be used as prompts. The
scorer expects `<case-id>.json` normalized standalone JSON responses in an
already existing response directory. Banner/prompt echo from `llama-cli` is
**not** JSON and needs a separately reviewed, fail-closed normalization step.
Do not write a real-host automation, native service, or bypass execution policy.

Required candidate object per case:

```json
{
  "case": "case-02",
  "answers": [
    {"probe_id": "recovered", "verdict": "unknown", "evidence_ids": []},
    {"probe_id": "recovery-failed", "verdict": "unknown", "evidence_ids": []},
    {"probe_id": "startup-failed", "verdict": "supported", "evidence_ids": ["S1"]}
  ],
  "explanation": ""
}
```

Strict structural checks reject duplicate JSON keys, malformed or oversized input,
nonexistent/duplicate evidence IDs, wrong case IDs, incomplete probes, and unknown
verdicts with citations. **Scoring** compares all probe verdicts and exact gold
citations, with separate counts for unsafe confident assertions and critical
decision errors. A wrong confident `conflicted` answer counts as unsupported;
an unjustified `unknown` is conservative abstention but can still be an
accuracy/critical completeness error.

The conservative **always-unknown** reference gives 12/30 correct probe verdicts
but makes no unsupported affirmative assertion. This is not an optimized or
gold-informed deterministic baseline, and no model beat it until actual observed
model responses and independent review demonstrate that. The evaluator's synthetic
all-gold answers are unit-test oracles, **not** measured local-model accuracy.

## Interpretation and acceptance gates

A zero exit from the structured scorer means **only** all structured verdicts and
citations matched its authored oracle. It **never** means `explanation` prose is
entailed or acceptable. Raw responses and all prose need blinded human review,
including source provenance, causal attribution, stale timestamps, and invented
lifecycle/device claims. Such review is explicitly NOT_PERFORMED by this script.

Do not integrate a model, run local inference unattended, grant write tools,
compare GPU speed, or mark the pilot successful based on a synthetic dataset.
A future operator-approved **CPU-only** trial may test these prompts on the
previously downloaded Qwen3-4B model, under the prior RAM/thread/no-server safety
boundaries, with full raw answer capture and no other host changes. Next record
end-to-end latency, per-probe error categories, free-text semantic failure rate,
and real marginal benefit vs concise deterministic source quotation. A cloud
baseline requires its separate privacy/cost approval.

## Environment and durable status

Prepared in historical, isolated Sandbox worktree
`C:\Work\home-hub-project\worktrees\local-llm-grounding-366-20261011`.
The repository's true GitHub `master` includes PR #379; this Sandbox checkout
may still be behind. **Do not publish the old branch ancestry or overwrite its
previous preserved files.** Native Sandbox Git is currently failing to execute;
do not try to weaken Windows application controls or claim final Git/Ruff checks
passed. Any later publication needs a fresh exact master/tree/file review and
separate commit/push/PR approval. No real-host, Latitude, Vault or device actions.
