import { automationStateFromStatus, houseStateLabel, activityLabel } from '$lib/stores/automation.js'

// A successful REST read confirms what HomeHub reported at receipt time. It
// does not certify underlying sensor freshness, presence, or a physical room.
export const HOME_CONTEXT_MAX_AGE_MS = 45000

const HOUSE_STATES = new Set(['away', 'home', 'winding_down', 'sleeping'])
const ACTIVITIES = new Set(['general', 'working', 'gaming', 'watching', 'cooking', 'relax', 'social', 'idle'])

/** @param {unknown} input */
export function validateHomeContextResponse(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) return null
  const data = /** @type {Record<string, unknown>} */ (input)
  if (typeof data.house_state !== 'string' || !HOUSE_STATES.has(data.house_state)) return null
  if (!Object.hasOwn(data, 'activity') ||
      (data.activity !== null && (typeof data.activity !== 'string' || !ACTIVITIES.has(data.activity)))) return null

  // Use the existing REST compatibility adapter only AFTER validating required
  // fields. Its defaults are intended for legacy UI, not live-source proof.
  const adapted = automationStateFromStatus(/** @type {Record<string, any>} */ (data))
  return {
    houseState: houseStateLabel(adapted.house_state),
    activity: adapted.activity ? activityLabel(adapted.activity) : null,
  }
}

/** @returns {{connected:boolean,generation:number,requestId:number,pending:boolean,receivedAt:number|null,reported:{houseState:string|null,activity:string|null}|null,failed:boolean}} */
export function newHomeContextSnapshot() {
  return { connected: false, generation: 0, requestId: 0, pending: false, receivedAt: null, reported: null, failed: false }
}

/** @param {ReturnType<typeof newHomeContextSnapshot>} state @param {boolean} connected */
export function homeContextConnectionChanged(state, connected) {
  if (state.connected === connected) return state
  return { ...state, connected, generation: state.generation + 1, pending: false, receivedAt: null, failed: false }
}

/** Invalidate a read on tab suspension; previous report remains historical. */
export function invalidateHomeContextRead(state) {
  return { ...state, generation: state.generation + 1, pending: false, receivedAt: null }
}

/** @param {ReturnType<typeof newHomeContextSnapshot>} state */
export function beginHomeContextRead(state) {
  if (!state.connected || state.pending) return { state, ticket: null }
  const requestId = state.requestId + 1
  return {
    state: { ...state, requestId, pending: true, failed: false },
    ticket: { generation: state.generation, requestId },
  }
}

/** @param {ReturnType<typeof newHomeContextSnapshot>} state @param {{generation:number,requestId:number}|null} ticket */
function validTicket(state, ticket) {
  return !!(ticket && state.connected && state.pending && state.generation === ticket.generation &&
    state.requestId === ticket.requestId)
}

/** @param {ReturnType<typeof newHomeContextSnapshot>} state
 *  @param {{generation:number,requestId:number}|null} ticket
 *  @param {unknown} body
 *  @param {number} nowMs */
export function acceptHomeContextRead(state, ticket, body, nowMs) {
  if (!validTicket(state, ticket)) return state
  const reported = validateHomeContextResponse(body)
  if (!reported || !Number.isFinite(nowMs) || nowMs < 0) {
    return { ...state, pending: false, receivedAt: null, failed: true }
  }
  return { ...state, pending: false, receivedAt: nowMs, reported, failed: false }
}

/** @param {ReturnType<typeof newHomeContextSnapshot>} state @param {{generation:number,requestId:number}|null} ticket */
export function failHomeContextRead(state, ticket) {
  return validTicket(state, ticket)
    ? { ...state, pending: false, receivedAt: null, failed: true }
    : state
}

/** @param {ReturnType<typeof newHomeContextSnapshot>} state
 *  @param {number} nowMs
 *  @param {number} [maxAgeMs]
 *  @returns {'disconnected'|'loading'|'unverified'|'recent'|'stale'|'unavailable'} */
export function homeContextStatus(state, nowMs, maxAgeMs = HOME_CONTEXT_MAX_AGE_MS) {
  if (!state.connected) return 'disconnected'
  if (state.receivedAt !== null && state.reported &&
      Number.isFinite(nowMs) && Number.isFinite(maxAgeMs) && maxAgeMs > 0 &&
      nowMs >= state.receivedAt && nowMs - state.receivedAt <= maxAgeMs) return 'recent'
  if (state.reported) return 'stale'
  if (state.pending) return 'loading'
  if (state.failed) return 'unavailable'
  return 'unverified'
}

/** @param {ReturnType<typeof newHomeContextSnapshot>} state @param {number} nowMs */
export function homeContextPresentation(state, nowMs) {
  const status = homeContextStatus(state, nowMs)
  if (status === 'recent') {
    const age = Math.max(0, Math.floor((nowMs - /** @type {number} */ (state.receivedAt)) / 1000))
    return {
      status, house: state.reported?.houseState ?? 'Unavailable',
      activity: state.reported?.activity ?? 'Not reported',
      note: `HomeHub REST response received ${age}s ago · not a sensor timestamp`,
    }
  }
  const labels = {
    disconnected: ['Disconnected', 'Disconnected', 'HomeHub connection unavailable'],
    loading: ['Checking…', 'Checking…', 'Reading HomeHub context'],
    unverified: ['Unverified', 'Unverified', 'No confirmed REST status yet'],
    stale: ['Unverified', 'Unverified', 'Previous REST report is no longer current'],
    unavailable: ['Unavailable', 'Unavailable', 'HomeHub context request failed'],
  }
  const [house, activity, note] = labels[status]
  return { status, house, activity, note }
}
