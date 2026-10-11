# HomeHub #366 — Deterministic explainer vs stronger read-only AI

> **Status:** Offline Sandbox research candidate; not integrated or published.
> **Owner:** [#366](https://github.com/agatte/home-hub/issues/366), Sensing &
> Intelligence. Deterministic evidence authority remains
> [#240](https://github.com/agatte/home-hub/issues/240).
> **Research contracts:** [AI semantic layer](AI_SEMANTIC_LAYER.md), and
> [fixed 10-case holdout](LOCAL_LLM_HOLDOUT_366.md).

## Product question

Does a stronger read-only generative model add sufficiently accurate, source-cited
interpretation beyond a deterministic HomeHub evidence explainer to justify
provider complexity, latency, privacy review, cost, and failure risk?

The old Qwen3-4B CPU result from #366 is evidence **against unattended Analyst
integration**, not a reason to select another model without a controlled
comparison. No generated output becomes HomeHub room, house-state, lifecycle,
scene, media, device or deployment authority.

## Minimal deterministic reference — deliberately conservative

`scripts/deterministic_evidence_baseline_366.py` reads the fixed sanitized
fixture via the merged strict JSON validator. **Prediction uses only case ID,
source label, evidence texts/IDs and probe texts/IDs; it never accesses gold
verdicts or criticality to decide an answer.** It creates:
- `answers/case-NN.json`: exact existing response schema, all 30 probes
  marked `unknown` and with no inferred citations or explanation prose.
- `evidence/case-NN.json`: 1:1 source-qualified copies of every supplied
  evidence text and every unassessed probe; explicitly NOT live observations.
- `evidence/case-NN.txt`: human-readable ID-tagged quotations with no
  synthesized causal claims, room assignment or action suggestions.

The **baseline makes no semantic decisions from free-text evidence**. Thus an
"unknown" answer is a *policy abstention*, not proof of lack of source evidence.
Quotations are source fidelity, not independent verification or causal reasoning.
For factual answers beyond quotations, a *typed* #240 policy trace with
pre-reviewed evidence-to-claim rules would be required; do not attempt arbitrary
natural-language entailment with a few ad hoc regular expressions.

### Measured, same 10-case fixed fixture

| Metric | Deterministic baseline | Qwen3-4B CPU run |
| --- | ---: | ---: |
| Inputs | Same 10 fixed sanitized cases | Same 10 cases |
| Exact schema-valid cases | 10/10 | 8/10 |
| Correct verdicts (invalid case = 0) | 12/30 | 20/30 |
| Exact verdict plus citations | 12/30 | 19/30 |
| Assertive unsupported conclusions | 0 | At least 2 in valid cases |
| Critical verdict misses | 10 abstention misses | At least 3 in valid cases |
| Model execution | None | 10 CPU invocations |
| Observed wall time | ~0.68 seconds for all cases in Sandbox | ~19.94 s per case |
| Normal desktop memory fit | No model RAM | Browser had to be closed |
| Explanatory capability | Exact 31 source quotations | Generative, but unreliable |

The baseline's time includes Windows Sandbox Python process startup and output
writing, **not** a matched Windows-host performance test. Its "critical misses"
are completeness errors due to abstention, not affirmative hallucinations.
For Qwen, automated error counters **exclude two invalid raw cases**, so
unsupported-claim and critical-miss totals are known lower bounds, not safe
zeroes. Source fidelity for the deterministic copies is mechanically testable;
it does not answer "why?" or establish a semantic benefit by itself.

The fixed cases and their gold labels are **published**. This is a regression
and feasibility benchmark, NOT an unseen or blinded generalization estimate.

### Reproduce without any model

In the existing isolated protected Windows Sandbox worktree, use the
already-installed Python interpreter and a **new unused** destination:

```powershell
$repo = 'C:\Work\home-hub-project\worktrees\local-llm-grounding-366-20261011'
$py = 'C:\Work\home-hub-project\main\.venv\Scripts\python.exe'
Set-Location $repo
& $py -B -m unittest discover -s tests -p test_deterministic_evidence_baseline_366.py
$out = Join-Path $env:TEMP ('hh-366-deterministic-' + [guid]::NewGuid().ToString('N'))
& $py -B scripts/deterministic_evidence_baseline_366.py --output $out
```

No network, model inference, service, user-data access or device command.
The output directory must not exist and will **never be overwritten or cleaned**
by the evaluator. Do not use real production logs or credentials as evidence.

## Stronger-model comparison — prepared, NOT RUN

**Independent execution matters:** the ongoing ChatGPT conversation has already
seen the public gold labels and Qwen failures. Scoring an answer generated
here as a "blind GPT-6 benchmark" would be invalid. The cloud provider,
exact independently invoked model/version, account/cost budget, retention/privacy
class, execution channel and approval are **not selected or authorized** by
publishing this research candidate.

A credible controlled comparison requires:

1. **Privacy/authority gate:** use only the sanitized source-inspired examples,
   with no raw audio/video/screenshots, personal logs, credentials, real host
   commands, writable tools, or production data. A separate explicit operator
   decision is needed before exporting evidence to an external provider or
   incurring metered API spend. Provider authorization must include retention
   and cost/token ceilings.
2. **Fair prompt parity:** hold constant the merged exporter version, all
   `case-NN.prompt.txt` files, four allowed statuses, evidence-ID schema, and
   parser/scorer. The model receives **only prompts**, never gold, critical
   flags, source repo access, or previous Qwen answers.
3. **Independent run:** invoke a fresh stateless model context or bounded API
   channel with specified model release, temperature, token cap, and per-case
   timeout. Capture original raw completions, schema failures, time and costs.
   No interactive guidance or automatic JSON repairs.
4. **Adjudicate claims:** score exact verdicts and references with the merged
   strict scorer, then independently review explanations and references for
   unsupported causal, room, lifecycle, device or rollout assertions. An
   invalid case counts as zero in exact scoring, never as a safe abstention.
5. **Avoid gold contamination:** pre-register an additional set of independently
   authored, evidence-provenanced cases with hidden gold *before* the fresh run
   if the goal is a new model go/no-go. Published #366 examples remain useful
   regression tests, not a private held-out evaluation.
6. **Decision rule:** select a generative read-only *advisory* capability only
   if it demonstrates added useful correct conclusions and evidence fidelity
   with zero unsupported **critical** assertions in independently reviewed
   evaluation, acceptable latency/cost/privacy, and a deterministic abstain
   fallback. No AI-generated inference may change physical or device state.

Do not promise "zero risk" from a finite benchmark. Any future HomeHub Analyst
prototype remains explicit, on-demand and read-only, with no actuation surface.

## Current gate and next owner action

- **Verified:** old Qwen quality NO-GO; this deterministic baseline is
  executable offline; 10/10 schema-valid abstentions, 12/30 exact matches,
  zero affirmative hallucinations, 31 exact source quotes.
- **Not verified:** independent stronger-model quality or cost/privacy,
  normal-workload inference coexistence, usefulness on unseen incident traces.
- **Next:** independent review of this uncommitted baseline and its docs; obtain
  **separate Git commit/push/PR authorization** for publication. Then obtain a
  concrete external provider, data privacy/cost authorization and unseen
  fixture design before the stronger-model run.
- **Do not:** merge, deploy, restart services, update Windows real-host controls,
  refresh the Obsidian Vault, install a local model, query live production,
  or operate lights/media/devices from this research.
