// Game Day store — fed by the central WS dispatcher (init.js) and primed
// from REST on page mount. Slice C of the Phase B fleet (docs/GAMEDAY_SPEC.md
// §4.4 / §4.5). Backend shape mirrors GameDayService's GameDayState +
// PlayEvent dataclasses serialized via dataclasses.asdict.

import { writable } from 'svelte/store'
import { apiGet } from '$lib/api.js'
import { HubSocket } from '$lib/ws.js'

/**
 * @typedef {Object} GamedayStoreState
 * @property {any | null} state          — GameDayState dict, or null when no game today
 * @property {any | null} lastPlay        — most recent PlayEvent dict (from gameday_play WS)
 * @property {any | null} lastCelebration — {sequence_key, started_at} from gameday_celebration WS
 * @property {Array<any>} schedule        — next-N upcoming game dicts from /api/gameday/schedule
 * @property {boolean} scheduleLoaded     — false until first /schedule REST call resolves
 */

/** @type {GamedayStoreState} */
const initial = {
  state: null,
  lastPlay: null,
  lastCelebration: null,
  schedule: [],
  scheduleLoaded: false,
}

/** @type {import('svelte/store').Writable<GamedayStoreState>} */
export const gameday = writable(initial)

/**
 * Route a `gameday_*` WebSocket message into the store. Called from the
 * central dispatcher in src/lib/stores/init.js once main session wires it
 * up post-merge. Slice C does not modify init.js.
 * @param {string} type
 * @param {any} data
 */
export function dispatchGamedayMessage(type, data) {
  if (type === 'gameday_state') {
    // Backend emits {"status": "no-game"} sentinel when no game is scheduled;
    // collapse that to null so consumers can `$gameday.state ?? fallback`.
    gameday.update((prev) => ({
      ...prev,
      state: data?.status === 'no-game' ? null : data,
    }))
  } else if (type === 'gameday_play') {
    gameday.update((prev) => ({ ...prev, lastPlay: data }))
  } else if (type === 'gameday_celebration') {
    gameday.update((prev) => ({ ...prev, lastCelebration: data }))
  }
}

/**
 * Start a Game-Day-only live feed for isolated presentation surfaces.
 * Avoids bootstrapping unrelated kiosk stores while preserving live WS state.
 */
export function initGamedayFeed() {
  // Prime from REST immediately, then keep only Game Day state live over WS.
  // This intentionally avoids the full kiosk store bootstrap on the isolated
  // prototype route (lights/Sonos/camera/weather/activity are unrelated here).
  fetchGamedayInitial()

  const socket = new HubSocket(
    (msg) => {
      const { type, data } = /** @type {{ type: string, data: any }} */ (msg)
      if (type === 'gameday_state' || type === 'gameday_play' || type === 'gameday_celebration') {
        dispatchGamedayMessage(type, data)
      }
    },
    () => {},
  )
  socket.connect()
  return () => socket.close()
}

/**
 * Best-effort REST priming. Failures are swallowed because the WebSocket
 * feed may still provide state once the backend is available.
 */
export async function fetchGamedayInitial() {
  try {
    const state = /** @type {any} */ (await apiGet('/api/gameday/state'))
    gameday.update((prev) => ({
      ...prev,
      state: state?.status === 'no-game' ? null : state,
    }))
  } catch (_) {
    /* swallow — WS will fill in */
  }

  try {
    const schedule = /** @type {any} */ (await apiGet('/api/gameday/schedule'))
    gameday.update((prev) => ({
      ...prev,
      schedule: Array.isArray(schedule) ? schedule : [],
      scheduleLoaded: true,
    }))
  } catch (_) {
    gameday.update((prev) => ({ ...prev, scheduleLoaded: true }))
  }
}
