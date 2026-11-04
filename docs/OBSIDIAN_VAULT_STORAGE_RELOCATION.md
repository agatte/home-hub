# #489 Vault storage relocation: Sandbox preparation

Status on 2026-11-04: **SOURCE ONLY / NOT INSTALLED / NOT INSTALLABLE**.
Owner: [#489](https://github.com/agatte/home-hub/issues/489).
Local uncommitted evidence lives in worktree
`C:\Work\home-hub-project\worktrees\obsidian-vault-relocation-prep-489-20261104`,
branch `work/489-vault-storage-bundle-prep-20261104`, base
`674d92a7861dd70646f67ece6a7706380348134e`. Nothing was published.

The current concrete recipe, pins and gates are recorded in **Concrete offline
recipe update (2026-11-04)** below. The earlier template evidence is retained as
history; its pending-runtime gate is superseded by that update.

## Earlier template contract and deliberate limit (superseded below)

`scripts/prepare_obsidian_relocation.py` validates only supplied template bytes
and a canonical manifest with independently supplied manifest/file digest anchors.
It does not import or weaken the installed legacy validator. Exact candidate paths:

- Vault: `C:\Users\Anthony\Documents\HomeHub Vault Storage\HomeHub Knowledge Vault`
- Separate candidate namespace:
  `C:\Users\Anthony\AppData\Local\HomeHub\ObsidianMirror\relocation-489-template-v1`

`relocation-489-template-v1` is an explicit template release label, not a Git
commit. `source_commit` remains null. The two JSON templates contain pending
publication/runtime/launcher pin placeholders. They are review data, not runtime
source or an executable updater. No files are staged at these paths. No Python
runtime path can be supplied. Activation comparison always refuses. The old
`5fbc1dd...` directory and old Vault are rejected. Legacy installed release files
and its fixed validator remain unchanged.

The pure API accepts only the fixed member names and exact template bytes;
missing/extra members, traversal names, path objects, link descriptors, drift,
wrong pins and changed bindings refuse. It cannot certify filesystem links or
reparse points, ACLs, identity, real Python bytes, filesystem race resistance,
publication, or actual source provenance. Caller-supplied digest agreement is
byte identity only, not independent reviewer attestation. A final runtime needs
its own reviewed filesystem and token checks; this model must not be adapted
into an installer by merely filling placeholders.

## Native synthetic evidence and provenance

The two preexisting copied sources are retained byte-for-byte from read-only
worktree `C:\Work\home-hub-project\worktrees\obsidian-hidden-launcher-399-20261025`:

| Current source | Historical source | SHA-256 (both copies verified) |
| --- | --- | --- |
| `scripts/obsidian_relocation_hidden_process.cs` | `scripts/obsidian_hidden_process.cs` | `D868B8913F323925D4F7E97DEF98B80D075DCA85E0E17B1C12319F284588F0CB` |
| `tests/obsidian_relocation_hidden_smoke.cs` | `tests/obsidian_hidden_launcher_smoke.cs` | `047A4822CD1949A943BEC15580432B4C7C097B44B9E9233B84B493630A45B1E2` |

Historical sources were uncommitted; these hashes establish copy provenance,
not a claim of published source. `HiddenProcess` hides the window, redirects and
concurrently drains both streams, waits and propagates child exit status.

Run `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test_obsidian_relocation_synthetic.ps1`
in this exact Sandbox worktree. It refuses other account/workspace identities,
uses the existing .NET Framework64 v4.0.30319 csc.exe and creates fresh guest TEMP
outputs only. It builds `tests/obsidian_relocation_refusal_fixture.cs` as winexe;
that fixture has no child invocation, updater, host path, or installation mode.
Blank arguments return 78 because final pins are absent; any argument returns 64.
The separate historical smoke self-invokes only its synthetic exit-7 child.

Observed: GUI subsystem 2, synthetic child exit 7 propagated, blank-argument
refusal 78 and extra-argument refusal 64 all passed. Artifacts retained at
`C:\Users\WDAGUtilityAccount\AppData\Local\Temp\obsidian-489-synthetic-70a778397cbf44a999b7a9b5faf513a4`.
No actual updater invocation, Scheduler access, or Vault reads occurred.
This verifies process mechanics and refusal only, not a production launcher.

## Validation and recovery evidence

- Registry Status for `237a751dfe6540308f12eb2615163a1d`: completed,
  worker_alive false, codex_exit_code 0. No replacement worker launched.
- `C:\Tools\Python313\python.exe -B -m unittest discover -s tests -p test_prepare_obsidian_relocation.py -v`: six tests pass.
- `C:\Work\home-hub-project\main\.venv\Scripts\ruff.exe check --no-cache scripts/prepare_obsidian_relocation.py tests/test_prepare_obsidian_relocation.py`: passes.
- Native synthetic build/smoke above: passes.
- `git diff --check`: passes (new untracked sources also require review).
- Existing `test_obsidian_schedule_launcher.py` attempted via unittest: import
  fails on missing pytest. It is pytest-based, so unittest is not a substitute
  runner for its function/parameterized tests. No dependency installation or
  emulation attempted; that suite is **not validated** here.

Network retrieval was prohibited. The user's supplied #489 evidence (44 complete
named triples plus four standalone backups = 136; original 20261025 hidden EXE,
blank arguments, WorkingDirectory 5fbc1dd; 14:00 result 0) was not independently
reconfirmed and is not a new live-health claim.

## Next gates

1. Implement and review the new relocation-specific runtime and GUI launcher,
   preserving identity, reparse, exact membership/pin, target, and backup guards.
   The template model is a bounded design, not completion of that runtime.
2. Separately authorize source commit/publication. Record the actual published
   commit and exact source bytes; never invent a Git identity for changed files.
3. Finalize a distinct immutable release ID, complete runtime/Python/native EXE
   pins, host-specific manifest anchor, and provenance. Independently review all
   final artifacts, exact blank-argument action and new WorkingDirectory.
4. Separately authorize bounded host bundle staging, task action migration and
   physical Vault move, with fresh task/snapshot/backup evidence and a reviewed
   preservation/rollback plan. Preserve the original bundle and notes/settings.
5. Separately accept natural scheduled/sign-in execution, no-change/offline/app-open
   behavior, source seals, backups and personal content preservation.

No host-capable package, Host Bridge change, refresh, task change, migration,
service/task restart, commit, push, merge or deployment is authorized by this prep.
See [OBSIDIAN_PERSISTENT_VAULT.md](OBSIDIAN_PERSISTENT_VAULT.md) for existing gates;
dated replacement-release notes are historical, not current host evidence.

## Concrete offline recipe update (2026-11-04)

This section supersedes the earlier template-only contract and next-gate step 1
above. The original preview API/tests and native fixtures remain preserved.
Current result: **source recipe ready, no host-specific attestation, not installable yet**.
The legacy installed validator, bundle and native source have not been edited.

`bundle_recipe(old_modules, old_pins, old_native, identity, *, release=NEW_RELEASE,
bundle=NEW_BUNDLE, vault=VAULT)` accepts bytes and data only and returns fresh
memory-only module blobs, nine file digests, canonical manifest bytes and anchor,
canonical release-pins bytes and digest, and native launcher source bytes/digest.
There is no CLI, filesystem access, import/execution of generated runtime,
installation, token probe or directory creation. Caller identity is data, never
an authenticity assertion. All outputs remain unpublished local source evidence.

The fixed new release identifier is
`4fd42377c69901d5f7145857b3da3ef728e45107`, the SHA-1 of the ASCII literal
`HomeHub-489-vault-storage-20261104`. It is a **release label, not a Git SHA or
claim of historical source provenance**; SHA-256 independently pins source bytes.
This follows the baseline-label contract in OBSIDIAN_REPLACEMENT_RELEASE.md.
The exact bundle path is
`C:\Users\Anthony\AppData\Local\HomeHub\ObsidianMirror\4fd42377c69901d5f7145857b3da3ef728e45107`.
The exact new Vault remains
`C:\Users\Anthony\Documents\HomeHub Vault Storage\HomeHub Knowledge Vault`.

Input anchors, checked before transforming any source:

- Reviewed current `scripts/obsidian_launcher_pins.json` raw-byte SHA-256:
  `20c774e360bff84d94942f0600219806e5919564e97c7e02264dddc808f31f62`.
- Historical native source (read-only `obsidian-hidden-launcher-399-20261025`
  worktree, `scripts/obsidian_mirror_hidden_launcher.cs`) SHA-256:
  `4372e4d9f982f828bfbab79f308abbd83982130d3a548e24b9f27a7b7ebcac69`.
  This is source byte identity, not a published provenance or EXE hash.

The supplied dictionary must contain exactly the nine reviewed modules with
bytes values and matching old hashes. Missing, extra, aliases, traversal names,
non-bytes and tampering refuse. The pins file itself cannot be resealed by the
caller. Exactly one occurrence of
`SOURCE_COMMIT = "5fbc1ddbe2d42d6a1540704b58da75a921b1e7f5"` is replaced in
`launch_obsidian_mirror.py`; zero/duplicate occurrences refuse, and the prefix
and suffix remain unchanged. The other eight modules remain byte-identical.

| New pinned module | SHA-256 |
| --- | --- |
| create_obsidian_pilot.py | d79b6788ede512dcccaebe226ffa79d0621b7a1db6f68302514bcda21b14542a |
| launch_obsidian_mirror.py | c1f6b6d975d2d3c166b7a01219131f15c8175b6d06424386130b7ff69b2e391a |
| manage_obsidian_vault.py | 0fc3981bdad21fe384db3ceae99e46b2bbad142d941272a681430dda82157500 |
| obsidian_github_docs_source.py | 1d4cddd425c0f4f961fb20654851417aaae39c25429ba66e99208b9137450526 |
| obsidian_raw_blob_transport.py | 0b44b30519bf6ce7ae2065a51a2d210405290983e21cdb412ff4b48ea88e48d8 |
| obsidian_simple_mirror.py | de9a0b6cb5a5919e9832788b904145f6aa0eb1caaccbd5365990ff2d51f318e6 |
| obsidian_source_verifier.py | eabd0a292a5268903e8fa47b4ea4bc1c49af473ee27bd2324303a9ee2d4fdfbe |
| obsidian_verified_stage.py | a69a38ca77e8f5444911aca06a949ababd8f407bb8aba6f49baf0b6742f24682 |
| run_obsidian_simple_mirror.py | 4f8859954d96b6496660e2faacc19b3a9c7e44f7f9bca2b8032e2fbb5dfd3fef |

Canonical new pins-file SHA-256:
`9d8b4652a78a4c687cab1cfaf7567adac0daa553c0d478524d4934356e83bab7`.

Identity must have exactly `user_root`, `python`, `sid`, `python_sha256`.
The root is exactly `C:\Users\Anthony` and Python exactly
`C:\Users\Anthony\AppData\Local\Programs\Python\Python313\python.exe`.
Paths are compared as literal strings: normalization, case aliases, traversal,
old Vault/bundle and project/worktree substitutes refuse. SID must have the
ordinary S-1-5-21 form with four positive 32-bit components; interpreter digest
must be 64 lowercase hex characters. This validates shape/binding only, not
actual host identity, interpreter bytes, ACLs, reparse points or runtime health.

The canonical manifest uses exactly the existing keys
`{source_commit,user_root,sid,bundle,python,python_sha256,vault,files}`, sorted JSON
keys, compact separators, ASCII bytes and no trailing newline. New `source_commit`
and bundle agree with the new runtime constant. Its SHA-256 becomes the new
Anchor. The native source is pinned first, then only its exact fixed Bundle and
Anchor declaration literals are substituted once each. Blank-argument enforcement,
Python literal, quoted `-I -B` arguments and `HiddenProcess.Run(Python, arguments,
Bundle)` are preserved byte-for-byte. A later independent Sandbox-only check compiled the generated source as a GUI EXE and executed only its extra-argument refusal path; no real updater process was launched, and no EXE was installed.

Synthetic test identity ONLY: SID `S-1-5-21-111-222-333-1001`, interpreter digest
64 lowercase `a` characters. For these fictional inputs the manifest anchor is
`99baa0912d01a1fe38bf1190db25ed9e291bf408dc3e97d40439ccd3f43ae099`
and generated native source SHA-256 is
`548fe12aae51d768923d3a0e027bee1ea28ef4888b547eaebdd2c87ad9f85a5e`.
These are **not host pins** and must never authorize installation or a task action.
A real independently supplied context produces its own manifest and native-source
hash; independent review remains required.

### Current offline verification and remaining gates

- Both prior tasks `237a751dfe6540308f12eb2615163a1d` and
  `bf68a75514c94e87839637810ea33c89` reconfirmed completed, worker_alive false,
  exit 0 before writing. Registry enumeration found only current task
  `d7f6a460760143fe9833962647e1bc66` running for this workspace; its worker PID
  11812 was confirmed as an ancestor of this tool process. No duplicate launched.
- Specified Python 3.13 unittest discovery: **13 tests passed** (six preserved
  template tests plus seven concrete recipe tests). Tests read old module source and a self-contained base64 fixture of the
  historical native source (SHA-256 `4372e4d9f982f828bfbab79f308abbd83982130d3a548e24b9f27a7b7ebcac69`),
  use synthetic identity, parse generated runtime with AST without executing it,
  and check fixed output digests.
- Specified standalone Ruff executable with `--no-cache`: **passed** for both
  changed Python files. No dependency installation required.
- Native synthetic smoke rerun: GUI subsystem 2, child exit 7, no-argument refusal
  78 and extra-argument refusal 64 all passed. Guest-only artifacts retained at
  `C:\Users\WDAGUtilityAccount\AppData\Local\Temp\obsidian-489-synthetic-4313bb2790414aff9b74800a5aba5661`.
  This runs synthetic fixtures only and does not validate the generated launcher
  against a real bundle, interpreter, task or Vault.

Independent source review and explicit commit/publication authorization remain.
Then independently obtain/attest the host context and review final manifest,
native build and EXE hash, source provenance and blank-argument action. The old
published packager remains bound to its old runtime/pins; do not point it at this
recipe output and claim staging is supported. A separately reviewed compatible
staging procedure is required, including absent-directory, identity, interpreter,
ACL/reparse and exact-file checks. No installer is delivered by this recipe.

Host bundle staging needs its own explicit approval. Vault relocation and task
action migration need separately bounded approvals, preservation/rollback plans
and fresh content-seal, backup, task and identity evidence. Natural scheduled,
sign-in, offline/no-change/app-open and personal-content acceptance follow those
steps. The supplied 14:00 success and 136 complete names do not establish content
seals. No GitHub/network refresh, host action or publication occurred here.

### Independent review checkpoint (2026-11-04, after Codex completion)

ChatGPT moved the historical C# launcher baseline into
`tests/obsidian_hidden_launcher_baseline.b64` as a base64-encoded exact-byte
fixture, independently confirmed SHA-256
`4372e4d9f982f828bfbab79f308abbd83982130d3a548e24b9f27a7b7ebcac69`.
The tests no longer depend on a separate uncommitted historical worktree.
Independent rerun: **13/13 unittest tests passed**, Ruff passed, and
`git diff --check` passed; branch/HEAD unchanged.

A distinct *generated-source* Windows Sandbox smoke test (not the preexisting
inert refusal fixture) produced the new native launcher C# from synthetic
identity, compiled it with the existing C# helper using .NET Framework csc.exe
as a GUI PE (subsystem **2**), and executed it **only with an extra argument**.
The executable refused with **exit 1 before any File.Exists or Python child**.
The actual no-argument launch path, bundle staging and Vault were not run.
The tested generated-source SHA-256 was
`548fe12aae51d768923d3a0e027bee1ea28ef4888b547eaebdd2c87ad9f85a5e`,
and the *synthetic-only* manifest anchor was
`99baa0912d01a1fe38bf1190db25ed9e291bf408dc3e97d40439ccd3f43ae099`.
Disposable evidence is retained at the exact Sandbox guest TEMP path
`C:\Users\WDAGUtilityAccount\AppData\Local\Temp\hh489-generated-gui-h7i7yddv`;
no cleanup was performed. **These hashes are not host release approvals.**

This preparation remains **uncommitted, unpublished, and not installed**.
The real Windows task still points at the old pinned bundle and the new Vault
parent does not yet exist. The physical move, task pause/action re-pin,
new bundle installation, and Obsidian rebind all require separate attended,
explicitly authorized host steps with fresh seals and protected-set evidence.

### Independent release-readiness review (2026-11-04, after 15:00 ET)

Separate from the Codex authoring tests, ChatGPT verified repository authority,
worker completion, the original immutable nine-file source pins, canonical
manifest encoding against `package_obsidian_schedule.manifest_bytes`, and the
same fixed-version/absolute-path validator contract. The isolated branch and
HEAD remain unchanged; no host bundle, task, Vault, or backup operation occurred.

One additional offline regression was added to
`tests/test_prepare_obsidian_relocation.py`: the generated and digest-verified
Python launcher is loaded under an inert non-`__main__` module name, then its
existing `validate_spec` is exercised against the synthetic new-release
manifest and altered legacy release/bundle/path values. No `main()` call,
network source acquisition, host filesystem probe, or updater invocation
occurs. **14/14** recipe tests pass; Ruff passes.

The repository's existing Windows venv contains a working pytest **module**;
direct invocation of its `pytest.exe` shim was unhelpful, but
`C:\Work\home-hub-project\main\.venv\Scripts\python.exe -B -m pytest`
works. Result from
`tests/test_obsidian_schedule_launcher.py`: **67 passed**. A first
mirror+task-migration run reported 12 failures caused by
`ModuleNotFoundError: test_obsidian_github_docs_source` because the existing
test suite imports a sibling test module by bare name. The representative
failure passed after setting process-local
`PYTHONPATH=<isolated-worktree>\tests;<isolated-worktree>\scripts`.
A full rerun with that path explicitly set passed **59 tests and 26 subtests**
in `test_obsidian_simple_mirror.py` and `test_obsidian_task_migration.py`.
This is an invocation correction, not a runtime code change or a bypass of
failing assertions. The original 12-failure run remains documented.

**Review verdict:** the **offline source recipe and synthetic packaging
contract** are prepared for separately approved Git publication and further
review. This is NOT a staged or operational release. The original packager
still pins the previous release; a new exact absent-directory staging tool,
real-host identity/Python digest evidence, versioned GUI build/review,
non-destructive attended Vault + 136-or-refreshed-siblings move,
task quiescence/action repin and Obsidian rebinding all require their
respective additional gates. The historical 14:00 healthy task result cannot
be assumed current after later hourly triggers.
