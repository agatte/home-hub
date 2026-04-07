// Thin fetch wrapper. The dashboard is LAN-only and talks to the same host
// FastAPI is serving from, so we use relative URLs everywhere — vite.config.js
// proxies /api, /ws, /health, /static to localhost:8000 during dev, and in
// production the SvelteKit build is mounted at / by the same FastAPI server.

/**
 * @param {string} path
 * @param {RequestInit} [init]
 */
export async function apiGet(path, init) {
  const res = await fetch(path, init)
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`)
  return res.json()
}

/**
 * @param {string} path
 * @param {unknown} [body]
 */
export async function apiPost(path, body) {
  const res = await fetch(path, {
    method: 'POST',
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) throw new Error(`POST ${path} failed: ${res.status}`)
  return res.json().catch(() => ({}))
}

/**
 * @param {string} path
 * @param {unknown} body
 */
export async function apiPut(path, body) {
  const res = await fetch(path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`PUT ${path} failed: ${res.status}`)
  return res.json().catch(() => ({}))
}

/**
 * @param {string} path
 */
export async function apiDelete(path) {
  const res = await fetch(path, { method: 'DELETE' })
  if (!res.ok) throw new Error(`DELETE ${path} failed: ${res.status}`)
  return res.json().catch(() => ({}))
}
