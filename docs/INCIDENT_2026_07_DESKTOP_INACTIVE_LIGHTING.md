# Desktop-Inactive Lighting Incident — July 14–31, 2026

## Status and context

- Investigation completed July 31, 2026; no production changes were made.
- Anthony remained home but did not use the desktop PC.
- The desktop bedroom camera and agents were unavailable; the Latitude living-room camera remained active.
- Away/geofence behavior was therefore not the cause.

## Executive summary

Home Hub stayed online on the Latitude and retained control of Hue, but lost most signals that explain *what Anthony is doing*. The Latitude camera could report living-room presence or absence, but could not observe the bedroom desk or distinguish working, gaming, and other desktop activities.

Two behaviors produced the unwanted colors:

1. User-selected modes expired after four hours even when no healthy semantic source could replace them. The engine exposed stale `idle`, whose daytime rule uses a green-tinted HSB payload despite being described as neutral.
2. Transit lighting treated sustained camera absence as repeated movement. It activated a path, hit its ten-minute timeout, restored automation, then re-armed against the same absence.

This is a resilience gap for the valid state **home, desktop inactive**. It is not Hue bridge drift or a consequence of the retired Claude monitoring loops.

## Evidence

Production history was inspected from July 14 through July 31 local time.

| Evidence | Count or observation |
|---|---:|
| Activity/mode events | 208 |
| Light adjustments | 24,088 |
| Scene activations | 10 |
| ML decision rows | 577,868 |
| Last sustained desktop reporting July 14 | about 20:28 |
| Desktop process/audio rows on most later days | 0 |
| Latitude camera rows | about 20,000–30,000/day |

The ten scene activations used `source=preset` and appear to be explicit user selections, not autonomous scene changes.

### Mode timeout and colored fallback

Dashboard and Alexa mode selections used the four-hour timeout. After expiry, the underlying mode was generally stale `idle`. Daytime idle sends every light:

```python
{"on": True, "bri": 220, "hue": 20000, "sat": 80}
```

That is visibly green HSB, not neutral white CT. `ambient_relax` could then fire immediately because idle dwell continued aging underneath the override. One July 28 transition reported 341,072 seconds (3.95 days) of idle dwell.

Representative July 31 sequence:

| Local time | Event |
|---|---|
| 11:47:56 | Working expired; all lights received daytime idle HSB |
| 12:22:12 | Cooking cleared to Auto; idle HSB applied again |
| 16:22:44 | Working expired |
| 16:22:45 | `ambient_relax` fired from accumulated idle dwell |
| 16:22:53 | Alexa restored Working |

### Repeating transit cycles

`TransitLightingService` uses ten seconds of absence as a walking trigger and a ten-minute timeout as runaway protection. L1 received 1,501 transit writes after July 15; 1,032 observed intervals were about 10–12 minutes apart. Transit must trigger from a fresh `present -> absent` edge, not an absence level, and must latch after timeout until fresh presence is observed.

## Capability boundary

The always-on Latitude owns the backend, database, Hue/Sonos, automation, scheduler, living-room presence/lux, Latitude media detection, and API/WS.

The desktop supplies process/input activity, bedroom desk presence and lux, screen sync and game events, audio classification, sleep watching, monitor brightness, and peripheral RGB. Home Hub runs without it but currently loses nearly all semantic context. Top-level health does not expose that distinction.

The retired Claude loops never owned lights or sensor inputs. Their retirement removed continuous verification, not automation capability. The desktop `pc_agent` processes are the relevant dependency.

## Additional findings

- Override-rate telemetry only counts the exact event source `manual`. Real user choices are `api:<client>` and `alexa:SetModeIntent`, so production reports zero despite roughly 2.4 rapid corrections/day in the recent window.
- Camera logging generated about 495,000 of the 577,868 ML rows. It logs every frame and marks repeated absent frames as applied even though the callback fires only at the threshold edge.
- Production SQLite was about 1.5 GiB with about 875 MiB on its freelist. Retention deletes rows, but disabled auto-vacuum means the file does not shrink. Reduce logging before any controlled maintenance compaction.
- Ambient audio repeatedly failed without a microphone but health still called it running. It reloaded its model on each retry.
- OpenRGB logged an unsupported-device message about every eight seconds.
- The lighting learner is protected: it trains only from explicit `ws`, `rest`, and `all_lights` triggers, not transit or automation churn.

## Recommended implementation plan

### P0 — Correctness — completed 2026-07-31

1. [x] Use semantic-source freshness as the desktop-unavailable safety gate.
   With no fresh non-idle replacement, preserve explicit user intent.
2. [x] Defer non-sleeping user-mode expiry until a fresh trusted replacement
   exists. Suspend idle dwell while the override is active and restart it if
   Auto returns to idle. Autonomous overrides retain their normal timeout.
3. [x] Make transit edge-triggered, once per confirmed presence session, and
   latch after activation/timeout until strong presence returns.
4. [x] Replace daytime idle HSB with CT-only neutral white
   (`{"on": true, "bri": 220, "ct": 250}`).

Regression coverage lives in
`TestDesktopUnavailableLightingPolicy` and
`tests/test_transit_lighting_service.py`.

### P1 — Resilience and observability

1. Expose capability health for desktop activity, desk presence, bedroom lux, audio, screen sync, and living-room presence.
2. Normalize actor/intent classes so dashboard and Alexa corrections count in autonomy metrics.
3. Treat future room sensors as occupancy evidence, not a way to guess PC-specific activity.
4. Show current signal freshness and actuator ownership in “why this mode.”

### P2 — Operational hygiene

1. Downsample camera decisions and correct `applied` semantics.
2. Add microphone-aware backoff and honest degraded health.
3. Rate-limit OpenRGB no-device logs.
4. Plan database compaction only after reducing write volume.
5. Keep documentation explicit about the Latitude/desktop split.

## Required regression coverage

- Desktop inactive while the user remains home preserves safe/manual lighting.
- Manual expiry without a trusted replacement does not expose stale idle.
- Idle dwell cannot cause immediate Relax after an override expires.
- Continuous absence produces at most one transit activation.
- Fresh presence followed by absence re-arms transit once.
- Daytime idle produces a CT-only payload.
- Override metrics include dashboard and Alexa actions.
- Camera logging is bounded and `applied` means a real action.
- Backing-off agents make capability health degraded.

## Decision record

> Being home without using the desktop is a normal operating state. Home Hub must remain predictable and visually neutral in that state; desktop agents may enrich automation but must not be prerequisites for stable lighting.
