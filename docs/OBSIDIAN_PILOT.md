# Obsidian documentation pilot (#355)

This is an optional **local, disposable viewer** for HomeHub's tracked Markdown,
not a second backlog, product-policy authority, live-health display, or editor of
the real repository. See [Project Admin Hub](PROJECT_ADMIN_HUB.md) and
[the owning issue](https://github.com/agatte/home-hub/issues/355).

## Source, isolation, and provenance

`scripts/create_obsidian_pilot.py` exports regular Git blobs from **one recorded
source HEAD**: `AGENTS.md` and `docs/**/*.md`. It does not copy uncommitted
edits, untracked files, symlinks, non-Markdown attachments, `.env`, databases,
or arbitrary repository files. Do not treat this as an independent secrets scan
of tracked documentation; keep the preview private and avoid cloud sync.

The destination must be a **new, nonexistent directory outside every Git
worktree**, under an already existing parent. The generator refuses overwrites
and never deletes older previews. Exported Markdown gets a read-only attribute
where supported, but generated `00-START-HERE.md` and `SNAPSHOT.md` are only
navigation/provenance aids. Obsidian may create a local `.obsidian` folder.
Edits to the preview never update the source repository.

For the protected Windows Sandbox development environment, use a unique guest
temporary folder rather than any host-mapped HomeHub project directory:

~~~powershell
$repo = 'C:\Work\home-hub-project\main'
$script = 'C:\Work\home-hub-project\main\scripts\create_obsidian_pilot.py'
$env:PATH = 'C:\Tools\Git\cmd;' + $env:PATH  # native Git, not the historical shim
$dest = Join-Path $env:TEMP ('homehub-obsidian-' + [guid]::NewGuid().ToString('N'))
& 'C:\Tools\Python313\python.exe' -B $script --repo $repo --output $dest
~~~

During unmerged worktree development, point `$script` at that worktree's
`scripts/create_obsidian_pilot.py`, while exporting from `$repo` (a clean
source checkout). The printed commit and `SNAPSHOT.md` state the actual source
SHA. A newer GitHub master or deployment may differ from the local checkout.

Open the output folder using **Obsidian → Open folder as vault**, then open
`00-START-HERE.md`. Use Obsidian's built-in search and local links. Do not
enable Sync, Publish, community plugins, automatic Git writes, or browser
extensions with new repository/credential permissions for this pilot.

## What to verify

1. The exported count and SHA match the intended Git HEAD; the source Git
   status is unchanged before and after export.
2. `AGENTS.md`, `docs/README.md`, `docs/PROJECT_SPEC.md`,
   `docs/EXECUTION_MAP.md`, and `docs/PROJECT_ADMIN_HUB.md` match their Git
   blob IDs. The generated landing note links to the included files.
3. No source `.env`, untracked documents, symlinks, raw media, or databases
   were copied. Non-Markdown relative links may not resolve.
4. Opening in Obsidian actually permits reading, navigating, and searching
   those pages; source files are not mutated. If Obsidian is unavailable,
   **record that gate as untested** rather than installing it without approval.

The generator does not install Obsidian, sync notes, collect telemetry, call a
backend, or touch HomeHub's runtime. A future permanent host installation,
refresh mechanism, writable vault, or documentation mirror is a new decision.
