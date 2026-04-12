import { writable } from 'svelte/store'

const IDLE_TIMEOUT_MS = 10000 // 10 seconds

/** Whether the user is currently idle (no mouse/touch/key for 60s) */
export const userIdle = writable(false)

let timeout = null

function resetIdle() {
  userIdle.set(false)
  clearTimeout(timeout)
  timeout = setTimeout(() => userIdle.set(true), IDLE_TIMEOUT_MS)
}

/** Call once on mount to start tracking user activity. Returns cleanup fn. */
export function initActivityTracking() {
  const events = ['mousemove', 'mousedown', 'touchstart', 'keydown', 'scroll']
  events.forEach((e) => window.addEventListener(e, resetIdle, { passive: true }))
  resetIdle()

  return () => {
    events.forEach((e) => window.removeEventListener(e, resetIdle))
    clearTimeout(timeout)
  }
}
