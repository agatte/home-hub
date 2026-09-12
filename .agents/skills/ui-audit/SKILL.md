---
name: ui-audit
description: Visually verify HomeHub dashboard or guest UI changes. Use for user-facing frontend review, responsive layout, or Threlte/Three.js rendering.
---

# HomeHub UI Audit

Use the running dev surface when available; otherwise use the backend-served
build. Inspect affected routes plus shared chrome only when relevant.

Check an appropriate desktop viewport and a narrow/mobile viewport. Verify layout,
navigation, loading/empty/error states, readable controls, media, and relevant
WebSocket state.

For Three.js/Threlte changes, confirm the canvas is nonblank, framed correctly,
responsive, and cleaned up across route changes. Prefer screenshots as evidence
for visual changes; build/check success alone is not visual acceptance.

Report `STATUS: ok|warn|error`, routes/viewports checked, and concrete findings.
