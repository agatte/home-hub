---
name: deploy-home
description: Publish and deploy HomeHub changes to the Latitude when the user asks to ship, push, deploy, or complete a release. Use only for HomeHub release work.
---

# Deploy Home

Use the repository's existing release path and current-session authorization.
Complete reversible preparation before asking for any remaining consequential
approval.

1. Inspect canonical Git state, intended diff, branch/ancestry, and relevant
   validation. Preserve unrelated work and the canonical untracked `=` file.
2. Run focused checks proportional to the changed surface. Confirm current CI
   when a pushed commit or branch is part of the release gate.
3. Commit or push only when that action is already authorized. Stage only the
   intended files; never force-push or hide unrelated failures.

For commit/push-only work, stop after the requested publishing step. For a
production deployment request, continue with the remaining steps.

4. Before production deployment, capture Latitude build/state and confirm no
   TRAVEL or RETURNING_HOME hold is active.
5. Deploy only through `scripts/deploy.sh` on the Latitude. Do not invent a
   parallel deployment path.
6. Verify production build rollover, `/health`, touched read surfaces, service
   state, and the post-restart journal window.

`home-hub-ambient.service` must never be restarted casually. If a changed file
would make the deploy script touch ambient, surface that fact before the live
action and follow the repository's explicit authorization boundary.

If deployment fails, follow the script's recorded rollback/result state before
taking any additional live action. Report the exact deployed SHA and any
remaining warning or limitation.
