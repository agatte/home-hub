// Correlation is ephemeral, never an operation key or physical confirmation.
// Shared state contains observations only; LightCard owns its local drag preview.
export function createLightCommands({ send, read, apply, report = (_id, _status) => {}, schedule = setTimeout,
  cancel = clearTimeout, uuid = () => Array.from(globalThis.crypto.getRandomValues(new Uint8Array(16)),
    (byte) => byte.toString(16).padStart(2, '0')).join('') }) {
  const listeners = new Set()
  const notify = (id, kind, data) => {
    for (const listener of listeners) listener(id, kind, data)
  }
  const reportOutcome = (id, status) => { notify(id, 'reset'); report(id, status) }
  const session = uuid()
  let sequence = 0
  let online = false
  const versions = new Map()
  const pending = new Map()
  const dirty = new Set()
  const bump = (id) => {
    const version = (versions.get(id) || 0) + 1
    versions.set(id, version)
    return version
  }
  const clear = (id) => {
    const command = pending.get(id)
    if (command) cancel(command.timer)
    pending.delete(id)
  }
  async function reconcile(id) {
    dirty.add(id)
    const version = bump(id)
    if (!online) return
    try {
      const light = await read(id)
      if (online && versions.get(id) === version && !pending.has(id)
          && light?.light_id === id && light.reachable === true) {
        notify(id, 'observation', light)
        apply(light)
        dirty.delete(id)
      }
    } catch {
      // Keep the last observation; failed reads never synthesize requested state.
      // Reconnect can try another read, never another physical command.
    }
  }
  return {
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener) },
    reconciliation(data) {
      // Server GET readbacks have no observation ordering fence. Never apply
      // their payload. Modern receipts already trigger a fenced client read;
      // a truly legacy receipt can only request a fresh, locally fenced read.
      if (data?.command_id == null && typeof data?.light_id === 'string'
          && !pending.has(data.light_id)) void reconcile(data.light_id)
    },
    set(id, state, correlationId) {
      clear(id)
      bump(id)
      if (!online) {
        reportOutcome(id, 'unavailable')
        return false
      }
      const command_id = correlationId ?? `${session}_${++sequence}`
      const timer = schedule(() => {
        clear(id)
        reportOutcome(id, 'uncertain')
        void reconcile(id)
      }, 10000)
      pending.set(id, { command_id, timer })
      try {
        if (send({ ...state, light_id: id, command_id }) === false) {
          clear(id)
          reportOutcome(id, 'uncertain')
          void reconcile(id)
          return false
        }
      } catch {
        clear(id)
        reportOutcome(id, 'uncertain')
        void reconcile(id)
        return false
      }
      return true
    },
    result(data) {
      // Match the latest command, including invalid receipts without fixture ID.
      const entry = [...pending].find(([, cmd]) => cmd.command_id === data?.command_id)
      if (!entry || (data.light_id != null && data.light_id !== entry[0])) return
      const [id] = entry
      clear(id)
      if (data.status !== 'acknowledged') {
        reportOutcome(id, data.status)
        void reconcile(id)
      }
      // ACK means transport + ownership persistence only. Wait for telemetry.
    },
    observe(light) {
      bump(light.light_id)
      dirty.delete(light.light_id)
      notify(light.light_id, 'observation', light)
      apply(light)
    },
    connection(value) {
      online = value
      for (const id of versions.keys()) bump(id)
      if (!value) {
        notify(null, 'reset')
        for (const id of pending.keys()) {
          dirty.add(id)
          clear(id)
          reportOutcome(id, 'uncertain')
        }
      } else {
        for (const id of dirty) void reconcile(id)
      }
    },
    close() {
      this.connection(false)
      dirty.clear()
    },
  }
}
