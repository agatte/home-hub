---
name: ui-audit
description: Visually verify HomeHub dashboard or guest UI changes in a browser, including responsive layout and Threlte/Three.js rendering. Use for user-facing frontend review or closeout, not backend-only work.
---

# HomeHub UI Audit

Use the running dev surface when available; otherwise use the backend-served
build. Inspect only routes affected by the change plus shared chrome when it is
involved.

Check an appropriate desktop viewport and a narrow/mobile viewport. Verify
layout fit, navigation, loading/empty/error states, readable controls, media,
and WebSocket-dependent state.

For Three.js/Threlte work, confirm the canvas is nonblank, correctly framed,
responsive, and cleaned up across route changes. Respect reduced motion when
the touched surface supports it.

Prefer screenshots as acceptance evidence for visual changes. Do not treat
successful build/check output as proof that the rendered composition is good.

Report `STATUS: ok|warn|error`, routes/viewports checked, and concrete visual or
interaction findings.