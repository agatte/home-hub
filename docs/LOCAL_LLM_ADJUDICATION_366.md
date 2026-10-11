# HomeHub #366 — Offline answer-key and citation adjudication guard

> **Status:** Uncommitted Sandbox research candidate. No production rollout,
> GitHub publication, fresh model call, or human-source attestation occurred.
> **Owner:** Sensing & Intelligence, [#366](https://github.com/agatte/home-hub/issues/366).
> The frozen regression scorer is
> `scripts/local_llm_holdout_366.py`; the first real natural replay capture
> remains separately evidence-gated under [#240](https://github.com/agatte/home-hub/issues/240).

## Why

The fixed Qwen3-4B benchmark had real grounding failures. The subsequent
stronger-model documentary experiment exposed **two distinct metric risks**:

1. A proposed gold verdict of *contradicted* was wrong when an old deployment
   marker did not prove absence of a later deployment. That gold was reconsidered
   **post-hoc**, not secretly changed in the original scorer.
2. A strict equality check rejected additional genuine source IDs and otherwise
   sufficient smaller citation sets. This is not permission to accept *any* extra
   IDs: each extra must be explicitly reviewed as relevant to that proposition.

The existing 10-case published-gold benchmark, the old 18-case Codex run, and
their originally reported numerical scores remain historically frozen.
This tool is separate and does **not** rewrite their gold, decisions or scores.

## What the tool checks (and what it does not)

`scripts/local_llm_adjudication_366.py` is a pure offline, stdlib-only
verification layer. It requires the exact raw fixture SHA-256, validates the
unchanged HomeHub #366 fixture and strict candidate response shape, checks
evidence-ID provenance and a human-*declared* citation policy, and reports
review/label drift explicitly.

For a non-unknown proposition, an answer passes citation adjudication only
when its refs include **one entire declared minimally sufficient set** and
every extra ref belongs to an **explicitly permitted supplemental ID set**.
Different minimum sets allow reviewed alternative paths to support a claim.
Missing mandatory evidence or extra unapproved IDs cannot be automatically
repaired, ignored, or papered over by a correct verdict. An unknown verdict
requires zero citations, even if individual evidence snippets were considered.
A changed verdict compared with the frozen fixture gold is always reported as
`gold_disagreements_requiring_separate_review`.

This tool does **NOT** determine whether text supports a proposition,
authenticate a reviewer URL, inspect a source link, establish live HomeHub
state, classify risk from prose, establish a natural replay capture, or approve
AI output for an action. `reviewed` is a **supplied human attestation claim**,
not proof of independent human adjudication or acceptance of source truth.
Results are `offline_advisory_adjudication_only`, with false
`device_or_production_authority` on every path.

If the manifest is a draft, contains unreviewed gold changes, or a model
response is malformed or fails one of its declared verdict/citation requirements,
`requires_review_or_reconciliation` stays true and the CLI exits nonzero.
An otherwise clean run does **not** authorize any model integration or claim
unseen natural-event generalization.

## Strict author-managed input format

The evaluation fixture retains the *existing* `version=1, cases=[...]`
format already validated by the merged #366 scorer. Reviewers prepare a
**separate** JSON manifest. Example of **one case / two probes only**:

```json
{
  "version": 1,
  "fixture_sha256": "<64 lowercase hex of the EXACT fixture bytes>",
  "review": {
    "status": "draft",
    "reviewer_kind": "unreviewed",
    "reviewer_reference": ""
  },
  "cases": [{
    "id": "doc-05",
    "source_url": "https://github.com/agatte/home-hub/issues/366",
    "source_scope": "dated_document",
    "probes": [
      {
        "id": "merged",
        "verdict": "supported",
        "minimal_citation_sets": [["E1"], ["E2"]],
        "permitted_additional_ids": ["E2"],
        "rationale": "Both records independently establish the merger."
      },
      {
        "id": "currently-live",
        "verdict": "unknown",
        "minimal_citation_sets": [],
        "permitted_additional_ids": [],
        "rationale": "A dated merge does not prove current service state."
      }
    ]
  }]
}
```

All case/probe IDs and ordering must exactly match the fixture. Evidence IDs
must exist in that case and may not duplicate. `source_scope` is one of
`dated_document`, `synthetic`, or `natural_capture` (the last is a label,
**not** proof of successful #240 acceptance).

After independent human/source review, `review.status="reviewed"` requires
`reviewer_kind="human"` and an HTTPS `reviewer_reference` to an accessible
review decision; a syntactically valid link is **not** authenticated by code.
Never use an AI self-declaration as human signoff. Preserve the prior draft,
source snapshots, reviewer disagreements and exact fixture/prompt hashes.
Do not send this manifest to the evaluated model; send only gold-free prompts.

## Offline usage

From the existing protected Sandbox, against files already placed in a
reviewed, bounded staging folder (no file writes or cleanup by the tool):

```powershell
$py = 'C:\Work\home-hub-project\main\.venv\Scripts\python.exe'
$repo = 'C:\Work\home-hub-project\worktrees\local-llm-grounding-366-20261011'
$script = Join-Path $repo 'scripts\local_llm_adjudication_366.py'

& $py -B $script --fixtures '<reviewed-fixture.json>' --manifest '<review.json>'
& $py -B $script --fixtures '<reviewed-fixture.json>' `
    --manifest '<review.json>' --responses '<existing-response-dir>'
```

The first command checks proposed gold declarations and reports disagreement
with frozen fixture gold. The second also scores existing model responses
against that separate policy **without changing them**. No cloud provider,
model runner, HomeHub runtime, network or device access exists in the tool.

Execute the focused regression suite:

```powershell
Set-Location $repo
& $py -B -m unittest discover -s tests -p test_local_llm_adjudication_366.py
```

## Current evidence/next gate

- Existing #366 comparison: Qwen3-4B **NO-GO** for unattended analysis.
- Cloud default-model Codex: originally **30/30** public gold verdicts and
  **23/24** author-scored additional synthetic verdicts; the latter has a
  documented **post-hoc gold correction**, not a new blind pass.
- Documentary source v5: **five source-anchored cases, 15 probes**, still
  **draft**; another model's source review was **not** independent human
  acceptance. No v5 model responses exist. Its prompt-only ZIP lacks gold.
- A real #240 natural replay cannot be assumed from historical GitHub summaries.

Next obtain independently inspected **human source/gold adjudication**, record
minimal sufficient and permissible supplemental citations *before* a new model
run, then agree an exact model/provider release, retention and capped usage.
A future read-only Analyst remains explicit, on-demand, source-linked and
non-authoritative; no automatic room, wake, lifecycle, light, Sonos, host or
deployment actions. Commit/push/PR, merge and production are separate gates.

The parent `docs/DETERMINISTIC_AI_COMPARISON_366.md` still contains historical
pre-merge/pre-benchmark status language. Reconcile it only as part of a
reviewed authorized Git PR, not as a silent edit on the old branch.
