// Thin fetch wrapper. The dashboard is LAN-only and talks to the same host
// FastAPI is serving from, so we use relative URLs everywhere — vite.config.js
// proxies /api, /ws, /health, /static to localhost:8000 during dev, and in
// production the SvelteKit build is mounted at / by the same FastAPI server.

import { addError } from '$lib/stores/errors.js'

/**
 * Wrap a fetch call with error reporting to the toast system.
 * Network errors and non-OK responses push a message to the error store.
 * @param {string} method
 * @param {string} path
 * @param {() => Promise<Response>} fetcher
 */
async function safeFetch(method, path, fetcher) {
  /** @type {Response} */
  let res
  try {
    res = await fetcher()
  } catch (e) {
    addError(`${method} ${path}: network error`)
    throw e
  }
  if (!res.ok) {
    addError(`${method} ${path}: ${res.status}`)
    throw new Error(`${method} ${path} failed: ${res.status}`)
  }
  return res
}

/**
 * @param {string} path
 * @param {RequestInit} [init]
 */
export async function apiGet(path, init) {
  const res = await safeFetch('GET', path, () => fetch(path, init))
  return res.json()
}

/**
 * @param {string} path
 * @param {unknown} [body]
 */
export async function apiPost(path, body) {
  const res = await safeFetch('POST', path, () => fetch(path, {
    method: 'POST',
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  }))
  return res.json().catch(() => null)
}

/**
 * @param {string} path
 * @param {unknown} body
 */
export async function apiPut(path, body) {
  const res = await safeFetch('PUT', path, () => fetch(path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }))
  return res.json().catch(() => null)
}

/**
 * @param {string} path
 */
export async function apiDelete(path) {
  const res = await safeFetch('DELETE', path, () => fetch(path, { method: 'DELETE' }))
  return res.json().catch(() => null)
}
