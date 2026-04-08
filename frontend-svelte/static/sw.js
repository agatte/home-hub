/**
 * Home Hub — Service Worker
 *
 * Enables "Add to Home Screen" on mobile devices.
 * Strategy:
 *   - HTML navigation (/, index.html): network-first so new builds load immediately
 *   - Hashed assets (/assets/*.js, *.css): cache-first (safe — filenames change on rebuild)
 *   - API / WebSocket / health: always network, no caching
 */

const CACHE_NAME = "home-hub-v3";
const SHELL_ASSETS = ["/"];

// Install — cache the app shell
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS))
  );
  self.skipWaiting();
});

// Activate — clean up old caches
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

// Fetch — network-first for HTML, cache-first for hashed static assets
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // Always go to network for API calls, WebSocket, and TTS audio
  if (
    url.pathname.startsWith("/api/") ||
    url.pathname.startsWith("/ws") ||
    url.pathname.startsWith("/health") ||
    url.pathname.startsWith("/static/")
  ) {
    return;
  }

  // Network-first for HTML — index.html must always be fresh so new JS bundles load
  if (
    event.request.mode === "navigate" ||
    url.pathname === "/" ||
    url.pathname.endsWith(".html")
  ) {
    event.respondWith(
      fetch(event.request).catch(() => caches.match(event.request))
    );
    return;
  }

  // Cache-first for hashed assets (JS, CSS, images)
  // Safe because Vite generates new filenames on every build
  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) {
        // Serve from cache and update in background
        fetch(event.request)
          .then((response) => {
            if (response.ok) {
              caches
                .open(CACHE_NAME)
                .then((cache) => cache.put(event.request, response));
            }
          })
          .catch(() => {});
        return cached;
      }
      return fetch(event.request);
    })
  );
});
