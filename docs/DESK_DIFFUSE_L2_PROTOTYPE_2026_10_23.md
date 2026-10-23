# #370 unwired pure L2 prototype

Local reversible prototype on `work/370-pure-l2-contract-20261023`, base HEAD
`c687b1a0b29955740d23bb5b201cb5fd53ab1bd9`, exact base tree
`817f798bfbade6c95278d9a1f8bfaf6d0dcd235b`. The supplied task identifies this
tree with reviewed draft PR #387 head `7c05cf9eb4c47dbaf7b1a1c17ba61b5945bf2422`
and reports green CI/conditional local approval. Those are supplied evidence,
not a new GitHub verification; this task used no network.

Authority: [PROJECT_SPEC.md](PROJECT_SPEC.md) desk visual comfort decision,
the supplied #370 owner/eligibility contract, and the limitations in the
[all-day simulation](DESK_COMFORT_ALL_DAY_SIMULATION_2026_10_23.md).
This adds only an offline callable in `backend/services/desk_visual_comfort.py`,
its pure tests, and this document. No callsites changed. No runtime activation,
sensor verification, monitor adjustment, Hue payload, or published floor exists.

## Contract

`DeskDiffuseL2Context` and `DeskDiffuseL2Decision` are frozen typed records.
The decision explicitly identifies L2 (`light_id="2"`) and this unwired policy.
`candidate_l2=None` means abstain/preserve the existing path, never switch off.
A candidate is brightness only, with no on/color/other-light fields.
The caller must supply a verified calibration floor for the matching period;
there is no default numeric floor or period table. Numbers are integral Hue
brightness units [1,254]; zero, negative, nonfinite, fractional, boolean and
out-of-range brightness inputs fail closed. Unknown period/composer fails closed.

| Activity | day | evening | night | late_night |
| --- | --- | --- | --- | --- |
| General | eligible | eligible | eligible | eligible |
| Working | eligible | eligible | eligible | eligible |
| Watching | eligible | eligible | eligible | eligible |
| Gaming | accepted Director only | accepted Director only | accepted Director only | accepted Director only |
| Relax | abstain | abstain | abstain | abstain |
| Social | abstain | abstain | abstain | abstain |
| Cooking | abstain | abstain | abstain | abstain |

Eligibility is conditional on Home and awake, fresh qualified **physical
Desktop Desk**, actual eligible screen viewing, verified matching calibration,
and trusted calibrated fresh room-qualified bedroom lux. This initial prototype
always requires lux qualification; it computes no ambient formula and accepts
no raw lux samples. All provenance/freshness/viewing flags are assertions from
an already trusted caller, not evidence validated here. Software Activity,
generic camera, Latitude or lux cannot establish physical Desk. API values use
lowercase Activities/periods and `house_state="Home"`.

Manual Activity selection alone is eligible and has no veto input. DND,
per-light L2 manual intent, scene/effect, transit, protected/external owner,
external-off/hard-off, stronger device ownership, missing rebrightening rights,
or a stale transition/epoch assertion veto. Rust and Game Day intentional
reactions abstain; only explicit `gaming_context="accepted_director"` opts in.
The trusted caller must classify that context correctly.

Static composition abstains whenever ScreenSync owns L2, regardless of lease
freshness. ScreenSync composition requires asserted L2 ownership, a current
accepted lease and an externally guaranteed same-frame guard. This proposes no
new writer and cannot replace the final lease/owner check. The synthetic epoch
test deliberately shows that an old immutable snapshot still passes if reused:
the boolean is not real dispatch fencing.

Original off is preserved. With permission, `target=min(floor,effective_cap)`
is returned only when it exceeds original brightness. A cap below original
always abstains, leaving cap enforcement to its existing owner. A floor above
cap reports `capped=True` after permission gates; a bounded lift is possible only
when cap permits it. Cap equal to original produces no lift. Earlier gate reasons
take precedence and do not claim numerical cap evaluation. No new policy rights
are created by calibration or capped status. Legacy owners remain authoritative.

## Evidence and remaining gates

All test calibration values are **synthetics, not actual physical calibration**.
Tests cover the 56 Activity/period/composer combinations, accepted versus rejected
Gaming contexts, each physical/lux/owner assertion, absent/mismatched calibration,
lease/frame/epoch rejection, off preservation, input/result immutability, invalid
brightness and monotonic clamping across the full Hue domain. This proves pure
eligibility/math only, not the health of upstream producers or physical comfort.

Future integration needs separately accepted numerical calibration and physical
surround/screen measurements for each period, trusted caller adapters, and owner
and transition race acceptance. Static placement would be after learner/weather
composition and before the final owner chokepoint. ScreenSync placement would be
inside the existing owned-frame floor/cap path with lease, EMA and final write
checks preserved. L5, Kitchen L3/L4, colors and display brightness are outside this
prototype. Runtime wiring and all consequential publication/deployment/device
actions need separate authorization.

Validation uses the existing venv Python with `-B`, Sandbox TEMP basetemp,
dotenv loading patched out before collection, network/file-DB audit guards,
plugin autoload disabled and `-p no:cacheprovider`; Ruff uses `--no-cache`.
Final local validation: **234 passed in 13.31s** (156 new policy tests plus 78
existing all-day simulation tests), no warnings. Ruff on both touched Python
files and `git diff --check` passed; Git's LF-to-CRLF advisory is not a whitespace
failure. Search found the new callable only at its definition and test import,
with no production caller.
No secrets/configuration, live producer, device, service/task, Host Bridge,
Obsidian source or other worktree was modified. No install, fetch, commit, push,
merge, deploy or destructive cleanup was performed.
