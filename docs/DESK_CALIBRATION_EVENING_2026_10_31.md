# Desk evening white/dark calibration evidence — 2026-10-31

**Status:** Human-reported, conditional physical observations. Test-only reference for
[#136](https://github.com/agatte/home-hub/issues/136) and
[#370](https://github.com/agatte/home-hub/issues/370), whose draft
[PR #387](https://github.com/agatte/home-hub/pull/387) is NOT deployed or activated.
No permanent brightness floors, per-content L5 targets, or runtime callers are
approved by this document.

## What was reported

The user adjusted the two lamps manually while at the Desk in Home/Evening.
The shaded left L2 at **70%** made a white ChatGPT page feel "okay" around 7:30 p.m.
With a dark page, the right clear L5 at approximately 22% looked dim; raising it
to **25%** had no meaningful improvement; at **30%** it improved the perceived
right-side and overall room lighting, and initially felt good.

**Critical later correction:** After several minutes with a **white screen**,
L5 **30% became too bright**. The user manually lowered L5 to **25%**, which
felt **much better**. Thus a single universal evening L5=30% recommendation is
contradicted by human feedback. Duration/adaptation and screen composition may
matter. This does not yet demonstrate the same effect with active ScreenSync.

| Screen | L2 manual | L5 manual | Subjective outcome |
| --- | ---: | ---: | --- |
| Dark | 70% | 25% | Right lamp still looked too dim |
| Dark | 70% | 30% | Improved room/right balance; felt good initially |
| White, after a few minutes | 70% | 30% | Too bright |
| White, after reduction | 70% | 25% | Much better |

These are rounded UI percentages, not authoritative fixture writes or Hue ACKs.
The measurements were sequential; sunlight, other lights, Activity, HomeHub
ownership, and visual adaptation were not independently controlled in each step.
Do not treat these ratings as eye-level lux, calibrated comfort thresholds, or
proof that monitor content caused specific bulb output changes.

## Safety and product implications

- Keep shaded **L2** useful as diffuse fill. L5 has clear housing and remains a
  subordinate accent; do not offset darkness by endlessly increasing it.
- [#251](https://github.com/agatte/home-hub/issues/251) sets **L5 evening
  autonomous ceiling 75/254**, about 29.5% of Hue's brightness range. A HomeHub
  rounded 30% manual setting can map to 76/254. That ceiling is **cap-only**,
  not a target or an instruction to override manually selected lamp values.
- The current authored/static simulation does not accept screen-content dwell
  or individual subjective assessments. Do not infer a content-driven automation
  policy from this small uncontrolled series. #243 separately owns representative
  ScreenSync color fidelity.
- Any later intervention must satisfy verified Home/awake, physical qualified
  Desk, calibrated bedroom lux, user-intent/scene/DND/away/off/transit/protected
  ownership, fresh and fenced ScreenSync source, final owner/ACK, hysteresis and
  bounded ramp. Source or lux uncertainty abstains. Manual settings persist
  until the user or an authorized owner clears them.
- A candidate L2 floor is not proven by this pair observation. Neither
  auto-learning nor new camera/screen capture or retention is authorized.

## Local verification

`tests/test_desk_human_calibration_evidence.py` encodes these conditional
human-reported outcomes as test-only evidence and verifies the existing L5
autonomous cap does not turn lights on or brighten them. It also records that
existing static Watching state is content-blind. These tests do **not** assert
human comfort scientifically or authorize a new actuation path.

This note was prepared in the isolated historical simulation worktree
`desk-all-day-sim-370-20261023`; its base is not current GitHub master. Before
publication or inclusion in draft PR #387, reconcile onto a fresh base, rerun
tests and obtain the applicable independent review and Git authorization.
