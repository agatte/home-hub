// Disable SSR for the entire app — this dashboard is a LAN-only SPA that
// depends on WebSocket + live polling. Client-rendered only.
export const ssr = false
export const prerender = false
