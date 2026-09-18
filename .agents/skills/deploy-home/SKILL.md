---
name: deploy-home
description: Publish or deploy HomeHub changes. Use when the user asks to commit/push a release or deploy to Latitude.
---

# Deploy Home

Use current-session authorization and the repository's supported release path.
Finish reversible preparation before asking for any remaining consequential step.

Inspect canonical Git state, intended diff/ancestry, and relevant validation.
Preserve unrelated work and the canonical untracked `=` file. Commit or push only
when authorized, stage only intended files, and do not hide unrelated failures.

For production deployment, capture current Latitude build/state, lifecycle
holds, and Git contract: clean tracked tree, `master`, permanent `origin`,
`master -> origin/master`, current HEAD, remote-tracking HEAD, and
`.last-deployed-sha`. A behind count is allowed before deployment because the
Latitude checkout is intentionally pinned to the last deployed SHA. Never
background-pull production merely to synchronize it.

Deploy only through `scripts/deploy.sh`. Verify build rollover, `/health`,
touched read surfaces, required service state, and the post-restart journal
window.

Do not casually restart `home-hub-ambient.service`. If the supported deploy path
would touch it, surface that before the live action. If deployment fails, follow
the script's recorded rollback/result state before taking another live action.

Report the exact published/deployed SHA and any remaining limitation.
