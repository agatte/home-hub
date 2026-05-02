import { readable, writable } from 'svelte/store'

/** @type {import('svelte/store').Writable<boolean>} */
export const connected = writable(false)

/**
 * @typedef {Object} DeviceStatus
 * @property {boolean} hue
 * @property {boolean} sonos
 */

/** @type {import('svelte/store').Writable<DeviceStatus>} */
export const deviceStatus = writable({ hue: false, sonos: false })

// Debounced view of the connection: only flips true after the WS has been
// down for a few seconds. Mobile WiFi handoffs and screen-lock cycles drop
// the socket briefly during reconnect — without a grace period the UI
// would flash a "Reconnecting..." banner every time the phone wakes up.
const DISCONNECT_GRACE_MS = 3000

/** @type {import('svelte/store').Readable<boolean>} */
export const connectionLost = readable(false, (set) => {
  let timer = null
  const unsub = connected.subscribe((isConnected) => {
    if (isConnected) {
      if (timer) { clearTimeout(timer); timer = null }
      set(false)
    } else if (!timer) {
      timer = setTimeout(() => {
        timer = null
        set(true)
      }, DISCONNECT_GRACE_MS)
    }
  })
  return () => {
    if (timer) clearTimeout(timer)
    unsub()
  }
})
