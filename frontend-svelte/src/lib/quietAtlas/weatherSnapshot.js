// Quiet Atlas #157: backend weather receipts are NOT proof of NWS observation freshness.
// Do not let cached provider data, failed reads, or connectivity changes appear authoritative.
export const WEATHER_REPORT_MAX_AGE_MS = 6 * 60 * 1000

/** @param {unknown} input */
export function validateWeatherReport(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) return null
  const envelope = /** @type {Record<string, unknown>} */ (input)
  if (envelope.status !== 'ok' || !envelope.weather ||
      typeof envelope.weather !== 'object' || Array.isArray(envelope.weather)) return null
  const data = /** @type {Record<string, unknown>} */ (envelope.weather)
  if (typeof data.temp !== 'number' || !Number.isFinite(data.temp) ||
      data.temp < -100 || data.temp > 150) return null
  if (typeof data.description !== 'string' ||
      !data.description.trim() || data.description.length > 100) return null
  if (typeof data.city !== 'string' || !data.city.trim() || data.city.length > 80) return null
  const feels = typeof data.feels_like === 'number' && Number.isFinite(data.feels_like) &&
    data.feels_like >= -100 && data.feels_like <= 160 ? Math.round(data.feels_like) : null
  return {
    temp: Math.round(data.temp),
    feelsLike: feels,
    description: data.description.trim(),
    city: data.city.trim(),
  }
}

/** @returns {{connected:boolean,generation:number,requestId:number,pending:boolean,
 *   reported:{temp:number,feelsLike:number|null,description:string,city:string}|null,
 *   receivedAt:number|null,failed:boolean}} */
export function newWeatherSnapshot() {
  return { connected: false, generation: 0, requestId: 0, pending: false,
    reported: null, receivedAt: null, failed: false }
}

/** @param {ReturnType<typeof newWeatherSnapshot>} state @param {boolean} connected */
export function weatherConnectionChanged(state, connected) {
  if (state.connected === connected) return state
  return { ...state, connected, generation: state.generation + 1, pending: false,
    receivedAt: null, reported: null, failed: false }
}

/** @param {ReturnType<typeof newWeatherSnapshot>} state */
export function invalidateWeatherRead(state) {
  return { ...state, generation: state.generation + 1, pending: false, receivedAt: null,
    reported: null, failed: false }
}

/** @param {ReturnType<typeof newWeatherSnapshot>} state */
export function beginWeatherRead(state) {
  if (!state.connected || state.pending) return { state, ticket: null }
  const requestId = state.requestId + 1
  return { state: { ...state, requestId, pending: true, failed: false },
    ticket: { generation: state.generation, requestId } }
}

/** @param {ReturnType<typeof newWeatherSnapshot>} state @param {{generation:number,requestId:number}|null} ticket */
function validTicket(state, ticket) {
  return !!(ticket && state.connected && state.pending && state.generation === ticket.generation &&
    state.requestId === ticket.requestId)
}

/** @param {ReturnType<typeof newWeatherSnapshot>} state
 *  @param {{generation:number,requestId:number}|null} ticket
 *  @param {unknown} body @param {number} nowMs */
export function acceptWeatherRead(state, ticket, body, nowMs) {
  if (!validTicket(state, ticket)) return state
  const parsed = validateWeatherReport(body)
  if (!parsed || !Number.isFinite(nowMs) || nowMs < 0)
    return { ...state, pending: false, failed: true, reported: null, receivedAt: null }
  return { ...state, pending: false, reported: parsed, receivedAt: nowMs, failed: false }
}

/** @param {ReturnType<typeof newWeatherSnapshot>} state @param {{generation:number,requestId:number}|null} ticket */
export function failWeatherRead(state, ticket) {
  return validTicket(state, ticket)
    ? { ...state, pending: false, failed: true, reported: null, receivedAt: null }
    : state
}

/** @param {ReturnType<typeof newWeatherSnapshot>} state @param {number} nowMs */
export function weatherPresentation(state, nowMs) {
  if (!state.connected) return { status: 'disconnected', message: 'HomeHub disconnected', report: null }
  if (state.reported && state.receivedAt !== null && Number.isFinite(nowMs) &&
      nowMs >= state.receivedAt && nowMs - state.receivedAt <= WEATHER_REPORT_MAX_AGE_MS)
    return { status: 'recent', message: 'Backend weather report received', report: state.reported }
  if (state.reported) return { status: 'stale', message: 'Previous weather report expired', report: null }
  if (state.pending) return { status: 'loading', message: 'Checking outdoor conditions', report: null }
  if (state.failed) return { status: 'unavailable', message: 'Weather report unavailable', report: null }
  return { status: 'unverified', message: 'No weather report verified', report: null }
}
