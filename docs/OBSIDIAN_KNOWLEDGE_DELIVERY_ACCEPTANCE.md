# HomeHub knowledge delivery: GitHub issue to Obsidian

**Owner:** Project Admin
**Acceptance issue:** [#422 — verify GitHub knowledge issue to docs to automatic Obsidian mirror](https://github.com/agatte/home-hub/issues/422)
**Related operating workflow:** [KNOWLEDGE_WORKFLOW.md](KNOWLEDGE_WORKFLOW.md), [#365](https://github.com/agatte/home-hub/issues/365)
**Automatic mirror owner:** [#399](https://github.com/agatte/home-hub/issues/399)
**Verification marker:** `HOMEHUB-KNOWLEDGE-DELIVERY-422`

## Intended workflow

1. ChatGPT/Codex checks the relevant current GitHub issues, tracked specifications and live repository state before acting. A GitHub issue records ownership, discussion, implementation status, evidence and acceptance.
2. When the outcome merits durable documentation, the assistant prepares a focused change to the **canonical Git repository**. The normal review, CI, commit, publish and merge authorization gates still apply.
3. The existing ordinary-user Windows Task Scheduler mirror checks verified GitHub `master` on its hourly/sign-in schedule. When there is a new authenticated forward commit, it mirrors allowlisted Markdown under `docs/` and `AGENTS.md` into **`HomeHub Source` inside the existing HomeHub Knowledge Vault**, after preserving a verified previous managed snapshot.
4. Obsidian can read the mirrored note whenever the user opens the Vault. It does **not** need to be running for hourly refresh. The assistant does not directly write to the generated `HomeHub Source` folder.

GitHub **issue bodies/comments are not themselves copied into the Vault** by the current mirror. The issue is the task/evidence ledger, while this Markdown page is the actual canonical knowledge artifact. Nor is the Vault a durable write-back database, an independent AI memory, or an always-on agent.

## Acceptance check for issue #422

Once this page has been reviewed and merged into `master`, use **read-only evidence** to confirm:

- A later naturally scheduled task run succeeded, without manually launching the updater or changing the Windows execution policy.
- `HomeHub Source/docs/OBSIDIAN_KNOWLEDGE_DELIVERY_ACCEPTANCE.md` exists in the existing Vault and contains `HOMEHUB-KNOWLEDGE-DELIVERY-422`. Its bytes match the reviewed GitHub document at the sealed commit.
- The managed `.homehub-snapshot-manifest.json` is sealed and points to the expected merged GitHub source commit.
- The previous managed snapshot is retained in a verified sibling backup; personal notes outside `HomeHub Source` and Obsidian-owned `.obsidian` preferences are outside updater write scope.
- An ordinary later **no-change** hourly run does not create another backup or an incomplete refresh marker.

Record concrete physical results and any remaining offline, sign-in/reboot or Obsidian-open acceptance in the owning issues. Do not declare any unobserved case successful.

## October 31, 2026 acceptance checkpoint and next observation (#399)

The issue-to-reviewed-docs-to-unattended-Obsidian delivery under [#422](https://github.com/agatte/home-hub/issues/422) is complete. On October 31, a read-only operator audit verified the 65-file current managed snapshot and the latest preserved backup. Subsequent ordinary no-change hourly runs kept the backup count at 13. An in-session fingerprint comparison found all four Obsidian settings files unchanged across a successful scheduled no-change run. There were no personal files outside generated source and `.obsidian` at that checkpoint, so actual personal-note content preservation was not exercised.

**Pending forward-refresh observation marker:** `HOMEHUB-399-APP-OPEN-FORWARD-20261031`.

This marker provides an unambiguous way to check a future **natural forward update while Obsidian remains open**. The marker's presence in canonical Git documentation is not evidence that it reached the Vault. After a separately authorized reviewed merge, record the exact merged GitHub commit, expected file hash, a new naturally scheduled task run, the managed manifest and backup/seal state, and the operator's app-open document/search/navigation observation in [#399](https://github.com/agatte/home-hub/issues/399). Do not manually run the updater, edit generated `HomeHub Source`, alter connectivity, or restart Windows to make the test happen.

## Safety boundary

Never recreate the already-installed Vault to deliver a document, edit its generated `HomeHub Source` subtree directly, copy a GitHub issue body into that subtree by hand, or silently update Windows tasks, credentials, policies, backups or personal notes. A documentation merge permits the existing configured automatic mirror to process the reviewed source through its normal guarded operation; it is not a new host-administration authorization.
