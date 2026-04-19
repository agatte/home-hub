// Bootstraps the app on mount: fetches initial REST state into the stores and
// opens the WebSocket. Called from +layout.svelte's onMount. Returns a cleanup
// function that closes the socket — Svelte's onMount uses the returned value
// as its destroy hook.

import { HubSocket } from '$lib/ws.js'
import { apiGet, apiPost } from '$lib/api.js'
import { lights, setLightsFromList, applyLightUpdate, optimisticLightPatch } from './lights.js'
import { sonos } from './sonos.js'
import { automation } from './automation.js'
import { connected, deviceStatus } from './connection.js'
import { showMusicSuggestion, showMusicAutoPlayed } from './music.js'
import { showModeSuggestion, dismissModeSuggestion } from './modeSuggestion.js'
import { ambient } from './ambient.js'
import { camera } from './camera.js'
import { pipeline } from './pipeline.js'

/** @type {HubSocket | null} */
let socket = null

// Brief lock to prevent WebSocket mode_update from overwriting an optimistic
// update before the server confirms. Cleared after 2s or when a matching
// server confirmation arrives.
let modeUpdateLockUntil = 0

export function initStores() {
  // Initial REST fetches — best-effort, errors swallowed so the UI still mounts
  // if the backend is warming up.
  apiGet('/api/lights')
    .then((data) => setLightsFromList(/** @type {any} */ (data)))
    .catch(() => {})

  apiGet('/api/sonos/status')
    .then((data) => sonos.set(/** @type {any} */ (data)))
    .catch(() => {})

  apiGet('/api/ambient')
    .then((data) => ambient.set(/** @type {any} */ (data)))
    .catch(() => {})

  apiGet('/api/camera/status')
    .then((data) => camera.set(/** @type {any} */ (data)))
    .catch(() => {})

  apiGet('/api/automation/status')
    .then((data) => {
      const d = /** @type {any} */ (data)
      automation.set({
        mode: d.current_mode,
        source: d.mode_source,
        manual_override: d.manual_override,
      })
    })
    .catch(() => {})

  apiGet('/api/automation/pipeline')
    .then((data) => {
      const d = /** @type {any} */ (data)
      pipeline.set({ current: d.current, history: d.history || [] })
    })
    .catch(() => {})

  // WebSocket dispatch — parity with HubContext.handleMessage in the React app.
  socket = new HubSocket(
    (msg) => {
      const { type, data } = /** @type {{ type: string, data: any }} */ (msg)
      switch (type) {
        case 'light_update':
          applyLightUpdate(data)
          break
        case 'sonos_update':
          sonos.set(data)
          break
        case 'connection_status':
          deviceStatus.set(data)
          break
        case 'mode_update':
          // If a user just clicked a mode, ignore server updates briefly
          // to prevent the stale pre-override broadcast from overwriting
          // the optimistic update.
          if (Date.now() < modeUpdateLockUntil && !data.manual_override) {
            break
          }
          modeUpdateLockUntil = 0
          automation.set(data)
          break
        case 'music_suggestion':
          showMusicSuggestion(data)
          break
        case 'music_auto_played':
          showMusicAutoPlayed(data)
          break
        case 'mode_suggestion':
          showModeSuggestion(data)
          break
        case 'mode_suggestion_dismissed':
          dismissModeSuggestion()
          break
        case 'ambient_update':
          ambient.set(data)
          break
        case 'camera_update':
          camera.update((prev) => prev ? { ...prev, ...data, last_detection: data.detection } : prev)
          break
        case 'pipeline_state':
          pipeline.update((prev) => ({
            current: data,
            history: [...prev.history.slice(-29), data],
          }))
          break
        default:
          console.warn('[ws] Unknown message type:', type, data)
          break
      }
    },
    (isConnected) => connected.set(isConnected)
  )
  socket.connect()

  return () => {
    socket?.close()
    socket = null
  }
}

// ---------- Action helpers (parity with HubContext actions) ----------

/**
 * Set a single light's state. Optimistic update runs immediately, then the
 * command is sent over the WebSocket.
 * @param {string} lightId
 * @param {Record<string, unknown>} state
 */
export function setLight(lightId, state) {
  socket?.send('light_command', { light_id: lightId, ...state })
  optimisticLightPatch(lightId, /** @type {any} */ (state))
}

/**
 * @param {string} action
 * @param {Record<string, unknown>} [params]
 */
export function sonosCommand(action, params = {}) {
  socket?.send('sonos_command', { action, ...params })
}

/** @param {string} sceneId */
export async function activateScene(sceneId) {
  await apiPost(`/api/scenes/${encodeURIComponent(sceneId)}/activate`)
}

/**
 * @param {string} text
 * @param {number} [volume]
 */
export async function speakText(text, volume) {
  await apiPost('/api/sonos/tts', { text, volume })
}

/** @param {string} mode */
export async function setManualMode(mode) {
  // Lock out stale WebSocket updates for 2s while the server processes
  modeUpdateLockUntil = Date.now() + 2000
  // Optimistic highlight — update store immediately before server confirms.
  automation.update((prev) => ({
    ...prev,
    mode: mode === 'auto' ? prev.mode : mode,
    manual_override: mode !== 'auto',
  }))
  try {
    await apiPost('/api/automation/override', { mode })
  } catch (e) {
    // Revert optimistic update on failure
    modeUpdateLockUntil = 0
    console.error('Mode override failed:', e)
  }
}

/** @param {string} title */
export async function playFavorite(title) {
  await apiPost(`/api/sonos/favorites/${encodeURIComponent(title)}/play`)
}
