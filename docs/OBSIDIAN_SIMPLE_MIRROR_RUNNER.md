# #399 one-shot simple mirror evaluation

This candidate wraps the merged `scripts/obsidian_simple_mirror.py` contract.
It is OFF by default. It does not install or activate anything, schedule work,
grant host approval, bootstrap a Vault, repair interruptions, or change the
permanent Vault operating procedure in [OBSIDIAN_PERSISTENT_VAULT.md](OBSIDIAN_PERSISTENT_VAULT.md).
The task's accepted simplified contract supersedes older recovery-framework
proposals for this runner; those historical proposals are not prerequisites.

`scripts/run_obsidian_simple_mirror.py` requires exactly one of `--check` or
`--apply`, an explicit absolute `--vault`, and an exactly matching
`--expected-vault`. There is no default target or environment-based approval.
Use the exact native path spelling: normalized aliases, relative paths, UNC
paths, device names, short-name spellings, and linked/reparse ancestors are
refused. Managed source must already have a valid sealed manifest.

`--check` reads only the managed snapshot and sibling interruption-marker names
locally, then uses the anonymous GitHub API over authenticated HTTPS to pin
master, verify forward ancestry, retrieve root/docs tree metadata and recheck
the ref. The CLI fetches Markdown bytes separately from the fixed
`raw.githubusercontent.com/agatte/home-hub/<40hex-commit>/<allowlisted-path>`
origin. Paths are validated and segment-encoded; redirects are refused, TLS
verification is enabled, requests use a 12-second timeout and reads are bounded
by the verified tree file size (maximum 3 MiB). Exact length and Git SHA-1 blob
OID checks still apply. There is no REST blob fallback on raw failure.
Forward acquisition uses six REST metadata requests regardless of file count;
an identical commit uses five because no compare is needed. Raw requests still
occur per file and may independently be unavailable or limited. Library callers
and injected API fixtures retain their existing REST blob behavior unless an
explicit `blob_source` is supplied.
Acquired content stays in memory even when a newer version is available.
It creates no stages, locks, temporary files, receipts or backups.
Direct CLI execution also disables Python import-cache writes. An approval
flag combined with check is refused. Source unavailability and partial evidence
fail closed; a local snapshot alone never establishes current GitHub state.

`--apply` additionally requires `--approve-local-evaluation` and calls the merged
`run_once` exactly once after local preflight. That library reacquires verified
source and revalidates local evidence. Its unchanged-source path writes nothing.
The approval flag expresses caller intent only: actual host operations still need
separate authorization. The original runner implementation was validated only
with Sandbox TEMP Synthetic Vaults, not real Vault operations or live network.
The separately reported real-host unelevated `--check` returned exit 3; its exact
HTTP failure cause remains unknown because CLI output bounds errors. The former
58-file REST content path required 64 REST calls on a forward check, exceeding
the stated 60/IP/hour anonymous budget even at full quota. This structural
defect does not establish the cause of that specific host failure.

Output is one bounded JSON object, containing fixed status strings and, on
success, source SHA labels. Exception text, paths, source content and transport
payloads are not printed. Argument errors use argparse's exit 2 and usage output.

| Exit | Meaning |
| --- | --- |
| 0 | `no_change` or `updated` |
| 1 | `update_available` (check only; no write approval) |
| 2 | Invalid arguments or `refused_or_failed_review_evidence` |
| 3 | `source_unavailable` (includes incomplete/untrusted GitHub evidence) |
| 4 | Unexpected `operation_failed_review_evidence` |

Exit 2 can also represent a filesystem failure during apply. A failed apply may
have written partial evidence; preserve it and obtain manual review before any
retry. No automatic repair, rollback or evidence cleanup is provided. Obsidian
may remain open under the library's cooperative model, but mixed versions and
check/replace races remain possible. This is not a globally atomic transaction
or security boundary. Personal notes, `.obsidian`, and historical backups are
outside the managed traversal.

Validation lives in `tests/test_run_obsidian_simple_mirror.py` and
`tests/test_obsidian_raw_blob_transport.py`, with mocked
GitHub transport and TEMP Synthetic Vaults only. It checks attempted mutations
as well as byte preservation for read-only and refusal paths. No real-host
ACL, sharing-handle, watcher, live GitHub, or permanent Vault acceptance is
claimed. Next gate: review the uncommitted candidate, then separately authorize
publication and any future host evaluation. No scheduler activation is included.

The separate [scheduled mirror candidate](OBSIDIAN_SCHEDULE_CANDIDATE.md) records
the accepted hourly-plus-login cadence, the OFF-by-default pinned in-process
launcher, explicit bundle preparation and pure disabled task XML builder.
Registration and activation remain unimplemented, separately authorized gates.
