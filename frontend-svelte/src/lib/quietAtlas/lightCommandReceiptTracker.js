// Correlated single-fixture command results for the redesigned Home.
// "acknowledged" means bridge transport acknowledgement, NOT physical readback.
// The original Apartment controls continue using the legacy WebSocket path.

const RESULT_STATUSES = new Set(['acknowledged', 'denied', 'unavailable', 'uncertain', 'invalid'])
const TIMEOUT_MS = 12_000
const SESSION = Math.random().toString(36).slice(2, 10)
let nextCommandNumber = 0

function nextCommandId() {
  // Correlation only, never a credential or server-side authority.
  nextCommandNumber += 1
  return `lc_${SESSION}_${Date.now().toString(36)}_${nextCommandNumber.toString(36)}`
}

/**
 * @param {{
 *   onUpdate: (snapshot: Record<string, { status: string, commandId: string | null }>) => void,
 *   timeoutMs?: number,
 *   generateId?: () => string,
 *   schedule?: typeof setTimeout,
 *   cancel?: typeof clearTimeout
 * }} config
 */
export function createLightCommandReceiptTracker({
  onUpdate, timeoutMs = TIMEOUT_MS, generateId = nextCommandId,
  schedule = setTimeout, cancel = clearTimeout,
}) {
  /** @type {Map<string, { commandId: string, timer: ReturnType<typeof setTimeout> | null }>} */
  const pending = new Map()
  /** @type {Record<string, { status: string, commandId: string | null }>} */
  let statuses = {}
  let capable = false

  /** @param {string} lightId @param {string} status @param {string | null} [commandId] */
  function publish(lightId, status, commandId = null) {
    statuses = { ...statuses, [lightId]: { status, commandId } }
    onUpdate({ ...statuses })
  }

  function settle(lightId, commandId, status) {
    const entry = pending.get(lightId)
    if (!entry || entry.commandId !== commandId) return false
    if (entry.timer !== null) cancel(entry.timer)
    pending.delete(lightId)
    publish(lightId, status, commandId)
    return true
  }

  return {
    /** Capability is supplied by the server handshake, never inferred from a WS send. */
    setCapability(enabled) { capable = enabled === true },

    /** @param {string} lightId @param {Record<string, unknown>} state @param {(data: Record<string, unknown>) => boolean} send */
    submit(lightId, state, send) {
      if (pending.has(lightId)) return 'pending'
      if (!capable) {
        publish(lightId, 'unavailable')
        return 'unavailable'
      }
      const commandId = generateId()
      if (!/^[A-Za-z0-9_-]{8,64}$/.test(commandId)) {
        publish(lightId, 'unavailable')
        return 'unavailable'
      }
      // Register before send so even a synchronous fake transport cannot
      // cause a response to race the pending state registration.
      pending.set(lightId, { commandId, timer: null })
      publish(lightId, 'pending', commandId)
      let delivered = false
      try { delivered = send({ light_id: lightId, ...state, command_id: commandId }) === true } catch { /* offline */ }
      if (!delivered) {
        settle(lightId, commandId, 'unavailable')
        return 'unavailable'
      }
      // A server or socket may have immediately resolved it during send.
      const active = pending.get(lightId)
      if (active && active.commandId === commandId) {
        active.timer = schedule(() => settle(lightId, commandId, 'uncertain'), timeoutMs)
      }
      return 'pending'
    },

    /** @param {unknown} response */
    receive(response) {
      if (!response || typeof response !== 'object') return false
      const data = /** @type {{ command_id?: unknown, light_id?: unknown, status?: unknown }} */ (response)
      if (typeof data.command_id !== 'string' || !RESULT_STATUSES.has(/** @type {string} */ (data.status))) return false
      for (const [lightId, entry] of pending) {
        if (entry.commandId !== data.command_id) continue
        if (data.light_id !== undefined && data.light_id !== lightId) return false
        return settle(lightId, entry.commandId, /** @type {string} */ (data.status))
      }
      return false
    },

    disconnect() {
      capable = false
      for (const [lightId, entry] of [...pending]) settle(lightId, entry.commandId, 'uncertain')
    },

    reset() {
      capable = false
      for (const entry of pending.values()) if (entry.timer !== null) cancel(entry.timer)
      pending.clear()
      statuses = {}
      onUpdate({})
    },

    snapshot() { return { ...statuses } },
  }
}
