// #270 read-only Home history: log entries are not proof of presence or room.
export const HISTORY_RECEIPT_AGE_MS = 90000
/** @type {Readonly<Record<string, string>>} */
const LABELS = { general: 'General', working: 'Working', gaming: 'Gaming',
  watching: 'Watching', cooking: 'Cooking', relax: 'Relaxing', social: 'Social' }

/** @param {unknown} value */
function parseEventTime(value) {
  if (typeof value !== 'string' ||
      !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)?$/.test(value)) return null
  // Existing EventQueryService emits UTC SQLite timestamps, often without Z.
  const instant = Date.parse(/(?:Z|[+-]\d\d:\d\d)$/.test(value) ? value : value + 'Z')
  return Number.isFinite(instant) ? instant : null
}

/** @param {unknown} body */
export function parseRecentActivityPage(body) {
  if (!body || typeof body !== 'object' || Array.isArray(body)) return null
  const page = /** @type {Record<string, any>} */ (body)
  if (!Number.isSafeInteger(page.total) || page.total < 0 ||
      !Array.isArray(page.events) || page.events.length > 6) return null
  const items = []
  for (const record of page.events) {
    if (!record || typeof record !== 'object' || Array.isArray(record)) return null
    const timestamp = parseEventTime(record.timestamp)
    if (timestamp === null || !Number.isSafeInteger(record.id) || record.id < 0 ||
        typeof record.mode !== 'string') return null
    // Internal idle, retired away and unknown modes must not be shown as activities.
    if (!Object.hasOwn(LABELS, record.mode)) continue
    items.push({ key: `${record.id}:${record.timestamp}`, label: LABELS[record.mode], timestamp })
  }
  items.sort((a, b) => b.timestamp - a.timestamp)
  return { total: page.total, items: items.slice(0, 4) }
}

/** @returns {{connected:boolean,generation:number,requestId:number,pending:boolean,receivedAt:number|null,items:Array<{key:string,label:string,timestamp:number}>,total:number,failed:boolean}} */
export function newRecentActivityLog() {
  return { connected: false, generation: 0, requestId: 0,
    pending: false, receivedAt: null, items: [], total: 0, failed: false }
}

/** @param {ReturnType<typeof newRecentActivityLog>} state @param {boolean} connected */
export function recentActivityConnectionChanged(state, connected) {
  if (state.connected === connected) return state
  return { ...state, connected, generation: state.generation + 1,
    pending: false, receivedAt: null, items: [], total: 0, failed: false }
}

/** @param {ReturnType<typeof newRecentActivityLog>} state */
export function invalidateRecentActivity(state) {
  return { ...state, generation: state.generation + 1,
    pending: false, receivedAt: null, items: [], total: 0, failed: false }
}

/** @param {ReturnType<typeof newRecentActivityLog>} state */
export function beginRecentActivityRead(state) {
  if (!state.connected || state.pending) return { state, ticket: null }
  const requestId = state.requestId + 1
  return { state: { ...state, requestId, pending: true, failed: false },
    ticket: { generation: state.generation, requestId } }
}

/** @param {ReturnType<typeof newRecentActivityLog>} state @param {{generation:number,requestId:number}|null} ticket */
function validTicket(state, ticket) {
  return !!(ticket && state.connected && state.pending &&
    ticket.generation === state.generation && ticket.requestId === state.requestId)
}

/** @param {ReturnType<typeof newRecentActivityLog>} state
 * @param {{generation:number,requestId:number}|null} ticket @param {unknown} body @param {number} at */
export function acceptRecentActivityRead(state, ticket, body, at) {
  if (!validTicket(state, ticket)) return state
  const page = parseRecentActivityPage(body)
  if (!page || !Number.isFinite(at) || at < 0) {
    return { ...state, pending: false, failed: true, receivedAt: null, items: [], total: 0 }
  }
  return { ...state, pending: false, failed: false,
    receivedAt: at, items: page.items, total: page.total }
}

/** @param {ReturnType<typeof newRecentActivityLog>} state @param {{generation:number,requestId:number}|null} ticket */
export function failRecentActivityRead(state, ticket) {
  return validTicket(state, ticket)
    ? { ...state, pending: false, failed: true, receivedAt: null, items: [], total: 0 }
    : state
}

/** @param {ReturnType<typeof newRecentActivityLog>} state @param {number} nowMs */
export function recentActivityPresentation(state, nowMs) {
  if (!state.connected) return { status: 'disconnected', items: [], message: 'HomeHub disconnected' }
  if (state.receivedAt !== null && Number.isFinite(nowMs) && nowMs >= state.receivedAt &&
      nowMs - state.receivedAt <= HISTORY_RECEIPT_AGE_MS) {
    return { status: state.items.length ? 'recent' : 'empty', items: state.items,
      message: state.items.length ? 'Recent logged activity' :
        state.total > 0 ? 'No displayable activity in the recent log' : 'No activity recorded in the past 24 hours' }
  }
  if (state.receivedAt !== null) return { status: 'stale', items: [], message: 'Activity reading expired' }
  if (state.pending) return { status: 'loading', items: [], message: 'Reading activity log…' }
  return { status: state.failed ? 'unavailable' : 'unverified', items: [],
    message: state.failed ? 'Activity log unavailable' : 'Activity not yet verified' }
}

/** @param {number} timestamp */
export function recentActivityTime(timestamp) {
  return Number.isFinite(timestamp)
    ? new Date(timestamp).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
    : 'Time unavailable'
}
