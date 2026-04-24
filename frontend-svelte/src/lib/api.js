// Thin fetch wrapper. The dashboard is LAN-only and talks to the same host
// FastAPI is serving from, so we use relative URLs everywhere — vite.config.js
// proxies /api, /ws, /health, /static to localhost:8000 during dev, and in
// production the SvelteKit build is mounted at / by the same FastAPI server.

import { addError } from '$lib/stores/errors.js'

// Default per-request timeout. Long enough for the slowest legitimate
// endpoints (TTS synth+play ~3-4s, Last.fm-backed recommendations ~5-6s
// on cache miss); short enough that a true backend stall surfaces as an
// error toast instead of an indefinite UI freeze.
const DEFAULT_TIMEOUT_MS = 8000

/**
 * Wrap a fetch call with timeout enforcement and error reporting.
 * Network errors, timeouts, and non-OK responses each push a distinct
 * message to the error store.
 * @param {string} method
 * @param {string} path
 * @param {(signal: AbortSignal) => Promise<Response>} fetcher
 * @param {{ timeout?: number }} [options]
 */
async function safeFetch(method, path, fetcher, { timeout = DEFAULT_TIMEOUT_MS } = {}) {
  const ac = new AbortController()
  const timeoutId = timeout ? setTimeout(() => ac.abort(), timeout) : null
  /** @type {Response} */
  let res
  try {
    res = await fetcher(ac.signal)
  } catch (e) {
    if (timeoutId) clearTimeout(timeoutId)
    if (ac.signal.aborted) {
      addError(`${method} ${path}: timed out (${timeout}ms)`)
    } else {
      addError(`${method} ${path}: network error`)
    }
    throw e
  }
  if (timeoutId) clearTimeout(timeoutId)
  if (!res.ok) {
    addError(`${method} ${path}: ${res.status}`)
    throw new Error(`${method} ${path} failed: ${res.status}`)
  }
  return res
}

/**
 * Read the response body as JSON. Returns null for an empty body (HTTP 204
 * style) so write endpoints that don't echo a payload still resolve cleanly.
 * Surfaces a real parse failure (server bug producing malformed JSON) via
 * addError + throw — the previous .catch(() => null) swallowed those.
 * @param {string} method
 * @param {string} path
 * @param {Response} res
 */
async function parseJsonOrNull(method, path, res) {
  const text = await res.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch (e) {
    addError(`${method} ${path}: malformed JSON response`)
    throw e
  }
}

/**
 * @param {string} path
 * @param {RequestInit} [init]
 * @param {{ timeout?: number }} [options]
 */
export async function apiGet(path, init, options) {
  const res = await safeFetch(
    'GET', path,
    (signal) => fetch(path, { ...init, signal }),
    options,
  )
  return parseJsonOrNull('GET', path, res)
}

/**
 * @param {string} path
 * @param {unknown} [body]
 * @param {{ timeout?: number }} [options]
 */
export async function apiPost(path, body, options) {
  const res = await safeFetch(
    'POST', path,
    (signal) => fetch(path, {
      method: 'POST',
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
      signal,
    }),
    options,
  )
  return parseJsonOrNull('POST', path, res)
}

/**
 * @param {string} path
 * @param {unknown} body
 * @param {{ timeout?: number }} [options]
 */
export async function apiPut(path, body, options) {
  const res = await safeFetch(
    'PUT', path,
    (signal) => fetch(path, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    }),
    options,
  )
  return parseJsonOrNull('PUT', path, res)
}

/**
 * @param {string} path
 * @param {{ timeout?: number }} [options]
 */
export async function apiDelete(path, options) {
  const res = await safeFetch(
    'DELETE', path,
    (signal) => fetch(path, { method: 'DELETE', signal }),
    options,
  )
  return parseJsonOrNull('DELETE', path, res)
}
