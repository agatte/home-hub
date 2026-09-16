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
 * @property {any | null} viewerState     - media-clock-aligned GameDayState snapshot
 * @property {any | null} viewerSync      - viewer-clock authority/diagnostic status
 * @property {boolean} viewerSyncLoaded    - viewer-sync authority status has been resolved
 * @property {any | null} lastCelebration — {sequence_key, started_at} from gameday_celebration WS
 * @property {Array<any>} schedule        — next-N upcoming game dicts from /api/gameday/schedule
 * @property {boolean} scheduleLoaded     — false until first /schedule REST call resolves
 */

/** @type {GamedayStoreState} */
const initial = {
  state: null,
  lastPlay: null,
  viewerState: null,
  viewerSync: null,
  viewerSyncLoaded: false,
  lastCelebration: null,
  schedule: [],
  scheduleLoaded: false,
}

/** @type {import('svelte/store').Writable<GamedayStoreState>} */
export const gameday = writable(initial)

// REST priming and WebSocket delivery can race on mount. Revisions ensure a
// slower REST response never overwrites a newer live frame/status.
let stateRevision = 0
let viewerAuthorityRevision = 0
let feedGeneration = 0

/**
 * Route a `gameday_*` WebSocket message into the store. Called from the
 * central dispatcher in src/lib/stores/init.js once main session wires it
 * up post-merge. Slice C does not modify init.js.
 * @param {string} type
 * @param {any} data
 */
export function dispatchGamedayMessage(type, data) {
  if (type === 'gameday_state') {
    stateRevision += 1
    // Backend emits {"status": "no-game"} sentinel when no game is scheduled;
    // collapse that to null so consumers can `$gameday.state ?? fallback`.
    gameday.update((prev) => ({
      ...prev,
      state: data?.status === 'no-game' ? null : data,
    }))
  } else if (type === 'gameday_viewer_state') {
    viewerAuthorityRevision += 1
    gameday.update((prev) => ({
      ...prev,
      viewerState: data?.status === 'no-game' ? null : data,
    }))
  } else if (type === 'gameday_viewer_sync') {
    viewerAuthorityRevision += 1
    const invalidatesFrame = data?.reason === 'new_session' || data?.reason === 'backward_seek'
    gameday.update((prev) => ({
      ...prev,
      viewerSync: data,
      viewerSyncLoaded: true,
      viewerState: invalidatesFrame ? null : prev.viewerState,
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
  // A newly owned feed must not paint a retained frame from an earlier route
  // visit before current viewer authority is resolved. Invalidate any older
  // in-flight REST prime at the same time.
  const generation = ++feedGeneration
  gameday.update((prev) => ({
    ...prev, viewerState: null, viewerSync: null, viewerSyncLoaded: false,
  }))
  fetchGamedayInitial(generation)

  const socket = new HubSocket(
    (msg) => {
      const { type, data } = /** @type {{ type: string, data: any }} */ (msg)
      if (['gameday_state', 'gameday_viewer_state', 'gameday_viewer_sync', 'gameday_play', 'gameday_celebration'].includes(type)) {
        dispatchGamedayMessage(type, data)
      }
    },
    () => {},
  )
  socket.connect()
  return () => {
    if (feedGeneration === generation) feedGeneration += 1
    socket.close()
  }
}

/**
 * Best-effort REST priming. Failures are swallowed because the WebSocket
 * feed may still provide state once the backend is available.
 */
export async function fetchGamedayInitial(generation = feedGeneration) {
  // Resolve viewer authority before canonical score/clock. Pages fail safe
  // while this is unknown, preventing a canonical future-state flash on mount.
  const viewerAuthorityRevisionAtStart = viewerAuthorityRevision
  try {
    const viewerSync = /** @type {any} */ (await apiGet('/api/gameday/viewer-sync'))
    if (generation !== feedGeneration) return
    // /viewer-sync returns status + frame as one authority snapshot. If any
    // newer WS viewer status OR frame arrived while REST was in flight, keep
    // both live values together; never combine new authority with an old frame.
    if (viewerAuthorityRevision === viewerAuthorityRevisionAtStart) {
      gameday.update((prev) => ({
        ...prev,
        viewerSync,
        viewerSyncLoaded: true,
        viewerState: viewerSync?.viewer_state ?? null,
      }))
    }
  } catch (_) {
    /* WS may still resolve viewer authority; leave fail-safe status unknown. */
  }

  const stateRevisionAtStart = stateRevision
  try {
    const state = /** @type {any} */ (await apiGet('/api/gameday/state'))
    if (generation !== feedGeneration) return
    gameday.update((prev) => ({
      ...prev,
      state: stateRevision === stateRevisionAtStart
        ? (state?.status === 'no-game' ? null : state)
        : prev.state,
    }))
  } catch (_) {
    /* swallow ? WS will fill in */
  }

  try {
    const schedule = /** @type {any} */ (await apiGet('/api/gameday/schedule'))
    if (generation !== feedGeneration) return
    gameday.update((prev) => ({
      ...prev,
      schedule: Array.isArray(schedule) ? schedule : [],
      scheduleLoaded: true,
    }))
  } catch (_) {
    gameday.update((prev) => ({ ...prev, scheduleLoaded: true }))
  }
}
