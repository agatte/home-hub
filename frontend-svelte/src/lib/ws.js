// WebSocket client with exponential backoff reconnect. Ported from
// frontend/src/hooks/useWebSocket.js — same reconnect semantics (1s → 30s),
// same parse-error logging. Framework-agnostic: stores subscribe via
// onMessage() and the connection lifetime is managed by initStores() in
// lib/stores/init.js.

const MAX_RECONNECT_DELAY = 30_000
const INITIAL_RECONNECT_DELAY = 1_000

/**
 * @typedef {{ type: string, data: unknown }} HubMessage
 */

export class HubSocket {
  /**
   * @param {(msg: HubMessage) => void} onMessage
   * @param {(connected: boolean) => void} onConnectionChange
   */
  constructor(onMessage, onConnectionChange) {
    this._onMessage = onMessage
    this._onConnectionChange = onConnectionChange
    /** @type {WebSocket | null} */
    this._ws = null
    /** @type {ReturnType<typeof setTimeout> | null} */
    this._reconnectTimer = null
    this._reconnectDelay = INITIAL_RECONNECT_DELAY
    this._closed = false
  }

  connect() {
    this._closed = false
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${window.location.host}/ws`

    const ws = new WebSocket(url)
    this._ws = ws

    ws.onopen = () => {
      this._onConnectionChange(true)
      this._reconnectDelay = INITIAL_RECONNECT_DELAY
    }

    ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data)
        this._onMessage(message)
      } catch (e) {
        console.error('WebSocket parse error:', e)
      }
    }

    ws.onclose = () => {
      this._onConnectionChange(false)
      this._ws = null
      if (this._closed) return
      this._reconnectTimer = setTimeout(() => {
        this._reconnectDelay = Math.min(this._reconnectDelay * 2, MAX_RECONNECT_DELAY)
        this.connect()
      }, this._reconnectDelay)
    }

    ws.onerror = () => {
      ws.close()
    }
  }

  /**
   * @param {string} type
   * @param {unknown} data
   */
  send(type, data) {
    if (this._ws?.readyState === WebSocket.OPEN) {
      this._ws.send(JSON.stringify({ type, data }))
    }
  }

  close() {
    this._closed = true
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer)
      this._reconnectTimer = null
    }
    if (this._ws) {
      this._ws.close()
      this._ws = null
    }
  }
}
