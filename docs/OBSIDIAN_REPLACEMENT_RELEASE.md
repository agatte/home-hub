# HomeHub #399 — immutable scheduled mirror replacement release

**Status:** source-only candidate, not installed or operationally accepted.
**Owner:** Project Admin; [issue #399](https://github.com/agatte/home-hub/issues/399).
**Baseline:** GitHub `master` `5fbc1ddbe2d42d6a1540704b58da75a921b1e7f5`.

## Why this release is necessary

The installed task `HomeHub Obsidian Mirror Refresh` was physically enabled
with explicit approval and triggered hourly, but returned exit code 2.
The original, correctly hash-pinned Python launcher had an untyped Win32
`OpenProcessToken` call: passing a typed `HANDLE` from
`GetCurrentProcess` raised `ctypes.ArgumentError` before bundle
verification. This was reproduced on the live host by a read-only diagnostic
and independently on disposable Windows Sandbox; typed Win32 API prototypes
resolve it. This strongly explains the scheduled result but no actual
Scheduler action traceback has been captured.

## Independent immutable identities

- Original installed bundle folder / `source_commit`:
  `f91407d165fd1263319bbadc45586da3681560aa`.
- Proposed replacement bundle folder / `source_commit`:
  `5fbc1ddbe2d42d6a1540704b58da75a921b1e7f5`.
  This is a **fixed release baseline identifier**, not a claim that corrected
  source files existed in that historical Git tree. The patched source is
  reviewed independently by PR head, updated launcher SHA-256 and source pins.
- The `obsidian_launcher_pins.json` file seals all nine exact package files.
  `package_obsidian_schedule.py` still requires the independent pins-file
  hash and target/user/SID/Python runtime checks, and stages only into an
  **absent versioned directory**. The manifest anchor is derived from the
  actual host-specific manifest and must not be guessed.
- The old registrar `register_obsidian_mirror_task.ps1` is intentionally
  **frozen** to the old bundle. It is create-only and refuses existing tasks.
  It is **NOT a migration or installation command for the new version**.
  New release tests require fail-closed behavior on the newer launcher bytes.

## Remaining separate real-host authorization gates

1. Before any host write, independently review the exact new package pins,
   new version ID, real host user/SID and Python runtime, current scheduled
   task definition, current managed snapshot integrity and existing evidence.
2. Obtain a **separate approval** to stage the new pinned bundle under the
   exact absent new directory; preserve the original bundle unchanged. Use
   the reviewed `package_obsidian_schedule.py` staging guard and independently
   verify every file plus the resulting host-specific manifest hash.
3. Separately review an **action-only existing-task migration**. It must
   confirm no running instance and original action/triggers/identity/settings,
   then replace only the pinned Python action target/manifest anchor with the
   independently verified new bundle. This is **not yet implemented** as a
   reviewed host migration adapter. Do not use the old create-only registrar,
   edit the task ad hoc, change XML without a full read-back, or disable/enable
   the existing task speculatively.
4. With explicit host mutation approval, execute exactly one bounded action
   migration under the ordinary interactive user; inspect registered task
   freshly. On unknown results, **STOP**, preserve evidence, do not retry,
   delete, repair, or force a refresh.
5. Independently accept automatic hourly and sign-in execution, logon/logoff
   behavior, offline/no-change behavior, Obsidian-open behavior, prior
   managed-file seal and backup preservation, notes/settings retention,
   no unexpected stage/lock evidence, reboot persistence and DST/overlap.
   Keep #399 open until verified.

**Never** edit the managed `HomeHub Source` directly, overwrite a pinned
installed bundle, restart Windows, change policy or ACLs, or use Sandbox/Host
Bridge to mutate the real Windows task as part of this source-only PR.
