# Runtime and API

Use the Latitude's local backend as production truth.

Check `/health` first for `build_id`, device connectivity, stale tasks, event
logger drops, scheduler state, circuit breakers, and ML lane health.

Then inspect only touched or symptomatic read endpoints, commonly:
`/api/automation/status`, `/api/camera/status`, `/api/sonos/status`, lights,
learning, routines/scenes/effects, or agent-health surfaces.

For deploy regressions, compare production HEAD/build ID with the expected
commit and inspect service active timestamps. Confirm the deployment marker when
relevant.

Do not exercise live write endpoints merely to smoke-test them. Use focused
tests or read-side evidence unless the user explicitly requests a live write.

Report `STATUS: ok|warn|error`, the observed build/state, concrete failing or
stale surface, and the next diagnostic action.