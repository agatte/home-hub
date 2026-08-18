# Dashboard UI/UX Audit — 2026-08-18

## Purpose

This document preserves the current-state Dashboard UI/UX audit completed before the next large HomeHub frontend redesign. It is a durable product/design record, not an implementation specification and not a mandate to preserve the current UI.

Canonical evidence baseline for the audit: `master` at `20939141511b` (`Implement explicit Sleeping to Auto wake`). Historical screenshots, old issue wording, and prior visual prescriptions are supporting evidence only; current code and current product contracts outrank them.

## Executive conclusion

HomeHub's underlying capabilities have outgrown the current primary dashboard presentation.

The current Home experience behaves largely like a conventional smart-home control panel: permanent action/mode cards, permanent widgets, repeated legacy Mode presentation, and animated backgrounds doing much of the work of making the page feel dynamic. Meanwhile, the backend and broader product now model richer concepts such as House State, Activity, physical context, provenance, scene ownership, history, Game Day, music, journal/analytics, guest experiences, and contextual automation.

The redesign should therefore be treated as an information-architecture and interaction problem rather than a cosmetic restyle.

Before visual redesign begins, complete the bounded baseline reconciliation tracked by #156 and establish the clean frontend check/build baseline tracked by #31. The larger redesign is indexed by #157.

## Current frontend inventory

The Svelte frontend already contains substantially more capability than the Home page communicates. Current routes/components include, among other things:

- Home/dashboard controls and status widgets;
- Apartment visualization and light/scene/effect controls;
- Music controls, taste/discovery tooling, and manual Mode → Playlist mappings;
- Analytics and decision/learning visualizations;
- Game Day presentation;
- Settings and system/network configuration;
- Journal/history surfaces;
- Personality/mood-adjacent research/diagnostic UI;
- guest/event-facing surfaces;
- multiple animated/canvas/Three.js background or visualization systems.

This means the redesign should first decide which capabilities are primary, contextual drill-downs, advanced diagnostics, guest-only experiences, or legacy surfaces to retire. Do not infer importance from the fact that a route/component already exists.

## Findings that require reconciliation before redesign

### 1. House State + Activity are not first-class frontend concepts

The backend now exposes `house_state` and `activity` through `/api/automation/status` and live `mode_update` messages. The accepted user-facing model is:

- House State: Away, Home, Winding Down, Sleeping;
- Activity: General plus stronger activities such as Working, Gaming, Watching, Cooking, Relax, Social, etc.;
- inferred context is softer secondary information, e.g. `Likely: Getting Ready`;
- detector/internal `idle` is not a peer user-facing state and maps to General while Home.

The current frontend store and primary UI still center the legacy single `mode` concept. This is a product-truthfulness mismatch, not merely a naming issue. #156 owns the frontend reconciliation; backend house-state semantics remain owned by House State & Automation.

### 2. Home is structurally static

The current Home surface is dominated by persistent controls/widgets whose relative importance changes little with context. Legacy Mode is also repeated across multiple surfaces.

This makes the dashboard feel static even though HomeHub itself is increasingly contextual. The redesign should prioritize answers to questions such as:

- What is the House State?
- What is the current Activity?
- What changed recently?
- What is HomeHub doing now?
- Why did it choose that behavior?
- Is anything degraded or asking for attention?
- What control or suggestion is relevant right now?

Do not default to giving every possible action equal visual weight at all times.

### 3. Retired bed/posture concepts remain visible in Settings

Current Settings still exposes inactive posture/bed-zone tuning and copy that preserves the configuration in case bed detection returns. This conflicts with #80, which resolves the current product direction: dormant `zone=bed` assumptions should be removed rather than represented as a current/revivable capability.

#156 owns the immediate frontend cleanup. This audit does not change sensing architecture.

### 4. Network Settings expose misleading `.lan` affordances

Current frontend code already documents that Google Wi-Fi owns `.lan` and that `.local`/mDNS is the zero-config path, but the user-facing settings still prominently seed/present `.lan` names.

Reconcile the UX with the actual network contract in #156. Do not use the Dashboard workstream to redesign apartment DNS architecture.

### 5. Small current usability/accessibility defects exist

The audit found concrete baseline issues worth fixing without waiting for the redesign, including:

- mobile `ErrorToast` overlapping the persistent bottom navigation region;
- form controls that rely on placeholders rather than durable labels;
- some focus treatments that remove the browser outline without always supplying an equally clear replacement.

Fix confirmed current defects semantically. Do not turn #156 into a broad CSS cleanup.

### 6. Frontend validation is not fully enforced in CI

Repo guidance expects the current Svelte check/build path for frontend changes, while the current workflow does not clearly enforce both `npm run check` and `npm run build`.

#31 now owns a fresh canonical warning/check/build inventory plus appropriate CI enforcement once the real baseline is known. Historical warning lists are not proof that warnings still reproduce.

## Findings that belong to the larger redesign

### Home should be contextual rather than a permanent control grid

The most important redesign question is not "how should the cards look?" but "how should an intelligent apartment present itself when glanced at?"

The primary experience should adapt information hierarchy to current House State, Activity, context, recent changes, explanation/provenance, and attention needs. Controls remain available but should not automatically dominate the composition.

### Animated backgrounds are not binding design precedent

The current frontend contains substantial animation/background complexity. The user does not consider the present result compelling enough to justify treating it as a core identity.

Motion may remain where it communicates state, continuity, atmosphere, or delight, but the redesign should not assume every mode/activity needs a separate animated wallpaper. Context should change the composition and information behavior of the UI, not only its background.

### Temporal awareness should become more central

HomeHub already records substantial event/history evidence, yet the primary dashboard does little to explain how the current state emerged.

#14 Replay / Time Machine has therefore been reframed around House State + Activity + provenance history rather than legacy single-Mode transitions. Exact visual treatment should follow #157.

### Idle should become an ambient information state

Current inactivity behavior mainly removes useful UI to reveal the background. #15 has been reframed as a calm ambient/idle display that may surface clock/date, weather, now playing, restrained House State + Activity, and genuinely useful status/context.

The redesign should establish the visual language first; the old animated-background/card-carousel prescription is not binding.

### Navigation needs product classification

The frontend contains primary routes, hidden routes, diagnostics, research surfaces, and guest/event experiences. #157 should explicitly classify them as:

- primary destinations;
- contextual drill-downs;
- advanced/diagnostic tools;
- guest/event-only experiences;
- legacy surfaces to retire or replace.

Do not preserve current navigation merely because routes already exist.

### Legacy Music and Personality UI are not future product precedent

The current Music page centers manual Mode → Playlist mappings, while #135 defines Music Curator as broader contextual discovery without requiring manual mappings for every experience. Do not polish that mapping model into a hero surface before Music Curator semantics are settled.

The current `/personality` route exposes camera-derived Live Mood / Phase-A research-style concepts. #133 defines explicit-first temporary Mood Context with cautious inference. Treat the current route as legacy diagnostic/research UI rather than future product precedent.

Likewise, internal rollout/development language such as "Phase 3 exit gate" should not define the consumer-facing voice of HomeHub.

## Existing issue disposition after audit

- #31 — active baseline task: current check/build warning inventory plus clean validation/CI enforcement.
- #32 — parked. Historical Music/Settings card parity is not a current implementation target; revisit only after #157 establishes the new system.
- #36 — narrowed. Hue bridge-scene visibility already exists; remaining work is current scene provenance, eligibility, and policy integration.
- #14 — retained and strengthened around House State + Activity + provenance history.
- #15 — retained but reframed as an ambient idle display rather than a background-first screensaver.
- #25 — remains gated on Winding Down/Morning event semantics.
- #39 — remains gated on the current Music Curator/bandit role.
- #41 — remains evidence-gated on measured Latitude kiosk compositor performance.
- #55 — remains a separate CSP/runtime hardening issue.

New tracking created from this audit:

- #156 Dashboard pre-redesign baseline reconciliation.
- #157 Dashboard UI/UX modernization — contextual HomeHub experience.

Do not create a separate issue for every brainstormed redesign surface in advance. Split #157 into bounded implementation slices only after accepted design decisions provide concrete acceptance criteria.

## Recommended sequence

1. Complete #31 fresh validation inventory.
2. Complete #156 baseline reconciliation without broad visual redesign.
3. Capture representative current 1080p kiosk and narrow/mobile screenshots as baseline evidence.
4. Use #157 for design discovery: information architecture, contextual hierarchy, motion philosophy, navigation classification, and first accepted Home composition.
5. Implement the redesign in bounded vertical slices, starting with the shell/context model and Home rather than attempting a route-wide restyle.
6. Migrate secondary routes only after the new Home/shell establishes a stable design language.

## Guardrails

- Current code/specs outrank historical screenshots and old issue prescriptions.
- Dashboard UI owns presentation and interaction, not the underlying semantics of House State, sensing, lighting policy, Music Curator, or Game Day.
- Do not combine the baseline cleanup and visual redesign into one large diff.
- Preserve manual/safety/privacy authority when presenting or invoking controls.
- Accessibility and kiosk/mobile performance should be measured during implementation, not deferred as a final polish phase.
- Production CSP, deployment, service restart, migration, and runtime operations remain separate authorized work.
