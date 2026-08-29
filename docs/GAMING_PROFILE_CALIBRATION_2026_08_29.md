# Gaming Director profile calibration checkpoint — 2026-08-29

**Status:** design/simulation evidence; no production actuation  
**Umbrella:** GitHub #105  
**Foundation:** #203  
**First profile:** #204  
**Telemetry:** #205

This checkpoint turns the Gaming Director product contract into concrete profile-priority and lighting-simulation evidence while implementation is waiting for a high-confidence code pass.

## Evidence used

- Canonical HomeHub `master`: `7477ca4`.
- Current six-light topology: L1 living-room anchor, L2/L5 bedroom lamps, paired kitchen L3/L4, L6 Plant Wash.
- L6 real-room calibration: many useful architectural colors become meaningful around roughly 65–80% Hue brightness; very low values can disappear visually.
- Current generic Gaming/day base: L1=130, L2=240, L3/L4=30, L5=75, L6=90 at `ct=286` (~3500K).
- Current Rust/day profile: L1=120, L2=150, L3/L4=35, L5=105, L6=130 with saturated ember/moss/blue-violet colors.
- AMD Adrenalin `RGStats.db` current-local evidence and installed Steam manifests were inspected read-only on 2026-08-29.

The simple brightness indexes below are **not lux**. They are only the mean of six Hue brightness targets divided by 254, useful for comparing proposed compositions at a glance.

## Functional envelope candidates

| Context | L1 | L2 | L3 | L4 | L5 | L6 | Relative index |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Current generic Gaming/day | 130 | 240 | 30 | 30 | 75 | 90 | 39.0% |
| Weekday daytime target | 205 | 240 | 165 | 165 | 190 | 180 | 75.1% |
| Weekend daytime target | 185 | 225 | 140 | 140 | 170 | 185 | 68.6% |
| Evening target | 145 | 165 | 90 | 90 | 95 | 185 | 50.5% |
| Night target | 105 | 120 | 60 | 60 | 65 | 170 | 38.1% |
| Late-night target | 70 | 85 | 35 | 35 | 45 | 110 | 24.9% |

These are starting envelopes. A game profile may stay below a number on a glare-prone fixture, but it should not be able to collapse daytime usability without an explicit reason.

## Profile priority inventory

Priority is based on a mix of current play evidence, existing HomeHub integration, visual differentiation, and integration leverage. It is deliberately **not** a lifetime-playtime claim.

### Tier A — build/calibrate first

1. **RDR2** — current actively played title and strongest new visual-profile candidate. AMD currently records the F-drive executable with roughly 17 hours of sessions; #204 already owns it.
2. **OSRS / RuneLite** — promote ahead of Rocket League. HomeHub already has dedicated RuneLite process semantics, and RuneLite exposes a rich event API suitable for a small privacy-bounded plugin adapter. AMD records hundreds of hours against generic `java.exe`, but that row cannot safely be attributed entirely to RuneLite because other Java workloads share the binary.
3. **League of Legends** — lower current AMD playtime than RDR2, but highest semantic integration leverage because HomeHub already consumes champion identity and Riot exposes local live game/event data.
4. **Rust** — preserve and migrate rather than reinvent. It already has a full profile plus luma/damage/under-fire behavior; its daytime profile now conflicts with the new function-first weekday/day contract and is a useful migration test.

### Tier B — authored stable profiles after the first framework proves out

- **Oxygen Not Included** — currently installed; distinctive cyan/industrial-amber identity.
- **Strange Horticulture** — currently installed; excellent candle/ink/plum visual identity with low integration cost.
- **High On Life** — currently installed; neon cyan/magenta/violet can work well after dark but needs strong daytime saturation limits.
- **Realm of the Mad God Exalt** — currently installed; jewel-color identity, best as a restrained static profile first.
- **Planet Zoo** — AMD catalog evidence exists even though the current Steam manifest scan did not show it installed; keep as a warm savanna/botanical profile candidate when it returns to active play.

### Tier C — keep generic Gaming until play evidence promotes them

Current Steam manifests also show titles such as GTA V, Civilization VI, Stardew Valley, Raft, Valheim, Stray, It Takes Two, Overcooked, NBA 2K19, Rocket League, and Rust Staging. These do not need bespoke lighting merely because they are installed.

Profile work should follow actual play/usefulness rather than creating an unused catalog.

## RDR2 — Frontier / Campfire & Moonlight

The #204 direction remains the leading first profile.

- Weekday day: functional neutral white dominates; L6 may be warmer white or a very restrained copper wash.
- Weekend day: white L1/L2/L3/L4/L5 with L6 near the proven architectural band in copper/amber.
- Evening: warm/campfire family grows stronger while kitchen remains useful.
- Night: warm anchor plus one restrained moon-blue counter-accent.
- Late night: deep warm/copper/burgundy; cool accent becomes minimal.

Recommended first real-room candidate: **Weekend Balanced Frontier** — use the weekend functional envelope, keep L1/L2/L3/L4/L5 neutral, and make L6 the primary copper signature around bri 180–190.

## OSRS / RuneLite — Parchment, Rune & Amethyst

Avoid the easy mistake of making OSRS a green room. The stronger visual language is parchment/gold + rune blue/amethyst, with green reserved for rare content-specific use if ever justified.

| Context | Functional fixtures | Accent fixtures | Starting feel |
| --- | --- | --- | --- |
| Weekday day | L1/L2/L3/L4/L5 bright neutral 3500–4000K | L6 warm-white 3000K, bri ~175–185 | normal apartment, subtle old-world warmth |
| Weekend day | same bright neutral base | L6 muted antique gold/copper, bri ~180–190 | readable room with clear OSRS signature |
| Evening | L1/L2/L3/L4 warm-neutral; L5 restrained | L6 antique gold, optional low-sat rune-blue L5 | parchment/candle + rune depth |
| Night | warm L1 anchor, paired kitchen low/warm | L6 amethyst or deep gold; L5 low rune blue | magical without becoming an RGB cave |
| Late night | low warm functional base | L6 deep amber/burgundy; cool accent nearly absent | cozy bank/inn rather than nightclub |

Candidate stable colors for simulation only:

- parchment/gold: `#C39A52`;
- antique amber: `#B8792D`;
- rune blue: `#4F67A8`;
- amethyst: `#6F4C9A`.

### RuneLite telemetry direction

RuneLite's official event model makes OSRS a stronger telemetry candidate than Rocket League for HomeHub. Useful event classes include `GameStateChanged`, `GameTick`, `StatChanged`, `HitsplatApplied`, `ActorDeath`, and client loot events such as `NpcLootReceived`.

V1 should **not** react to every event. Candidate reactions:

- level-up: 2–3 second gold/amethyst celebration on L6 plus one secondary light;
- notable loot: brief gold accent only above an explicit value/rarity threshold;
- player death: short muted red/amber drop, no repeated flashing;
- low-health/damage: probably diagnostics/replay first; only actuate if it proves useful rather than stressful;
- login/logout: context only, no celebration.

The adapter should never stream or persist chat text, usernames, full inventory, or raw tick/event history by default.

## League of Legends — Champion Director

League should use the **champion** as the game signature rather than one fixed League palette.

Daytime candidate:

- preserve the bright functional envelope on L1/L3/L4;
- move most champion color expression to L6 plus a saturation-capped bedroom accent;
- avoid letting a very dark champion palette collapse L2/L5 task visibility.

Evening/night candidate:

- L1 remains warm/neutral anchor;
- L3/L4 stay paired and mostly warm-neutral;
- L2/L5 may carry the existing champion identity within glare/brightness caps;
- L6 may carry either the champion primary or a curated complementary family, but should not fight L2/L5 with three unrelated colors.

## Rust — migrate Rusted Ember into the new envelope

Current Rust/day is only ~37.7% on the simple brightness index and uses saturated ember/moss/blue-violet across the room. That was coherent under the older Rust-specific design, but it conflicts with the new weekday/day product rule.

Recommended migration:

- **Weekday day:** use the bright neutral functional envelope. Keep Rust identity mainly on L6 as a restrained ember/iron wash; L2 may retain luma-driven **brightness** without forcing the entire room into ember/moss color.
- **Weekend day:** allow L6 stronger ember and one low-saturation supporting accent while L1 and kitchen remain useful/neutral.
- **Evening/night:** preserve the proven Rusted Ember family and existing luma-driven L2 plus damage/under-fire behavior.
- **Late night:** preserve the existing deep ember behavior, subject to future global comfort caps.

Do not remove the existing Rust event system merely to make the architecture uniform. Migrate only where the generalized boundary improves consistency without losing proven behavior.

## Static-profile simulation queue

### Oxygen Not Included — Oxygen & Industry

- Day: neutral functional room; L6 low-saturation cyan or warm industrial-white accent.
- Evening/night: oxygen cyan + industrial amber; keep amber as the visual anchor so cyan does not make the room cold.
- No telemetry work unless a future mod offers a clearly valuable semantic with very low maintenance cost.

### Strange Horticulture — Candle, Ink & Plum

- Day: warm-neutral functional base, L6 muted amber/sepia.
- Evening/night: candle amber + restrained plum/amethyst; avoid room-wide moss green despite the botanical theme.
- Excellent low-risk static-profile candidate because the aesthetic is distinctive without needing events.

### High On Life — Alien Neon

- Day: neutral functional base; at most one restrained cyan/magenta L6 accent.
- Evening/night: cyan/magenta/violet can become much stronger, but L1 remains an anchor and L3/L4 remain functional.
- Strong saturation caps are required because the game's art direction can otherwise produce the exact daytime RGB-cave failure Gaming Director is intended to prevent.

### Realm of the Mad God Exalt — Jewel Chamber

- Day: bright neutral with a single jewel-purple or cyan accent on L6.
- Evening/night: jewel purple + cyan + gold; keep gold/warm neutral as the grounding element.
- Stable profile first; no need for packet/client-state integration.

### Planet Zoo — Savanna Sunset

- Day: bright warm-neutral with L6 savanna gold; no dominant green.
- Evening/night: sunset amber/terracotta with a restrained botanical secondary accent only if the room still reads warm and comfortable.
- Re-prioritize when actual current play evidence returns.

## Next calibration actions while implementation is blocked

1. Photograph/visually review RDR2 Weekend Balanced Frontier in the real room when convenient.
2. Build the same five-context numeric fixture table for OSRS, then calibrate the **weekend day** and **night** variants first.
3. Capture one normal RuneLite session's event-rate inventory **without lighting actuation** before selecting level-up/loot/death cooldowns.
4. Replay one League match's local `eventdata` into a dry-run event inventory before defining objective effects.
5. Compare current Rust/day against a neutral-envelope Rust/day simulation; after-dark Rust behavior is not presumed broken.
6. Do not spend implementation effort on Tier B/C profiles until #203 and #204 prove the resolver and calibration workflow.

## OSRS numeric candidate envelope

First exact simulation pass for later real-room review. These remain **proposals**, not accepted Hue values.

Reference color conversions:

```text
parchment/gold #C39A52 -> hue ~6959,  sat ~147
antique amber  #B8792D -> hue ~5972,  sat ~192
rune blue      #4F67A8 -> hue ~40745, sat ~135
amethyst       #6F4C9A -> hue ~48591, sat ~129
```

### Weekday day — functional first

```text
L1 bri205 ct250
L2 bri240 ct250
L3 bri165 ct250
L4 bri165 ct250
L5 bri190 ct250
L6 bri180 ct333
```

Brightness index: **75.1%**. No saturated color is required during a normal weekday day.

### Weekend day — Parchment & Gold

```text
L1 bri185 ct286
L2 bri225 ct286
L3 bri140 ct286
L4 bri140 ct286
L5 bri170 ct286
L6 bri185 hue5972 sat145   # restrained antique-gold wash
```

Brightness index: **68.6%**. L6 carries the identity while the rest of the room stays useful white.

### Evening — Candle & Rune

```text
L1 bri145 ct333
L2 bri165 ct333
L3 bri90  ct333
L4 bri90  ct333
L5 bri90  hue40745 sat75    # low-saturation rune-blue echo
L6 bri185 hue5972  sat170   # antique-gold architecture
```

Brightness index: **50.2%**. Blue is subordinate and localized; the apartment still reads warm.

### Night — Rune & Amethyst

```text
L1 bri105 ct370
L2 bri120 ct370
L3 bri60  ct370
L4 bri60  ct370
L5 bri65  hue40745 sat105
L6 bri170 hue48591 sat125   # amethyst architectural wash
```

Brightness index: **38.1%**. This is the first candidate that should feel overtly magical; reject it if the amethyst/rune pairing reads like generic RGB gaming.

### Late night — Inn Light

```text
L1 bri70  ct400
L2 bri85  ct400
L3 bri35  ct400
L4 bri35  ct400
L5 bri45  hue5972 sat80
L6 bri110 hue5972 sat150
```

Brightness index: **24.9%**. Cool color is removed; the signature collapses back toward low amber/gold comfort.

### OSRS first visual-review order

1. Weekend day — easiest proof that a game can have personality without dimming the apartment.
2. Night — determine whether amethyst + rune blue feels like OSRS or merely RGB.
3. Evening — tune the handoff between the two.
4. Weekday day — verify the 4000K functional target is bright without feeling office-like.
5. Late night — only after the future whole-apartment comfort envelope is reconciled.
