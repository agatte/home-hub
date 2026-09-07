---
name: homehub-research
description: Research future HomeHub capabilities, design ideas, Game Day experiences, or opportunities hidden in hardware/software Anthony already owns. Use for broad future-direction scans, focused idea probes, hardware-opportunity research, or Future_Development registry refreshes. Read-only by default; do not create GitHub issues, change accepted product policy, or actuate devices unless separately requested.
---

# HomeHub Research

Use `docs/Future_Development.md` as the durable research brief and idea registry.
`docs/PROJECT_SPEC.md` remains accepted product truth, and current GitHub issue
contracts own bounded tracked work. This skill discovers, evaluates, deduplicates,
and retains possibilities; it does not silently promote them into product direction.

## Research modes

Infer the smallest useful mode from the request:

- **Broad horizon scan** — deliberately search across all three research jobs in
  `Future_Development.md`; a user-supplied example is a lead, not the boundary.
- **Focused idea probe** — deeply test feasibility, novelty, current alternatives,
  and HomeHub fit for one candidate.
- **Hardware-opportunity scan** — look for capabilities hidden in installed,
  underused, spare, or possibly-unrecorded hardware before recommending purchases.
- **Registry refresh** — reconcile the research registry against current code,
  issues, external evidence, and accepted decisions; edit the registry only when
  the caller asks for a durable update.

## Workflow

1. Inspect canonical Git status first and preserve unrelated work plus root `=`.
2. Read the registry intro, status vocabulary, promotion flow, and only the job
   sections relevant to the request. Read the full registry for a broad scan.
3. Inventory current capability from relevant current code/specs before proposing
   a new component. Do not treat historical agent docs as current architecture.
4. Check current GitHub issue ownership before calling an idea new. Prefer
   `FOLDS INTO #N` over a duplicate issue when an owner already exists.
5. For current technology, standards, products, APIs, research, or feasibility,
   use fresh web evidence. Prefer primary documentation and original papers.
6. Separate facts from hypotheses. Mark immature techniques as `LAB`; do not
   launder interesting research into a production recommendation.
7. Preserve HomeHub authority rules: software evidence cannot invent a physical
   room, experimental sensing begins shadow-only, and no research result grants
   automation/device authority.
8. If the request is broad, actively seek ideas in all three jobs: smarter use of
   existing data/hardware; better experiences/design/Game Day; and surprising
   capabilities of owned or potentially-owned hardware. Do not pad with weak ideas.
9. If unknown household hardware could materially change a recommendation, ask
   only the smallest useful hardware question (for example spare phone, webcam,
   speaker, wearable, router, game peripheral, SBC). Do not demand a full inventory.

## Output contract

For a research pass, report the useful result rather than narrating every source.
Prefer these sections when they fit:

- **New findings** — the strongest genuinely useful or surprising ideas.
- **HomeHub fit** — what existing hardware/data/services make the idea plausible.
- **Dedupe / owner** — `TRACKED`, `FOLDS INTO`, `CANDIDATE`, `LAB`, or `PARKED`.
- **Cost class** — zero-purchase, uses hardware Anthony may already own, or would
  require new hardware. Existing-hardware-first is the default.
- **Evidence / uncertainty** — what is proven, what is only plausible, and the
  smallest experiment or observation that would resolve the uncertainty.
- **Promotion recommendation** — keep in registry, extend an existing issue, or
  propose a new issue only if Anthony has selected the idea.

When updating `docs/Future_Development.md`, place the idea under the correct job,
retain richer concept detail even when it folds into an existing issue, update
cross-links instead of duplicating prose, and refresh the review date when the
research checkpoint materially changes. Do not update `PROJECT_SPEC.md` unless
accepted cross-system product policy actually changes.

## Delegation guidance

The main session owns synthesis. Use one bounded Codex worker when parallel web
research or source extraction materially helps. Luna Low is appropriate for
inventory/dedupe/source gathering; Terra Medium is the default for broader
cross-source synthesis. Use multiple workers only for genuinely independent
research lanes. A worker should return evidence and candidate registry edits;
it should not create issues or implement the idea unless separately tasked.

## Guardrail against research anchoring

When Anthony gives one example of a future capability, treat it as one search seed.
For a broad scan, deliberately widen into unrelated domains and report the best
cross-domain findings. A successful scan may return fewer ideas if evidence is
weak; it must not return a long list of variations on the seed merely to appear
comprehensive.
