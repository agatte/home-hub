// Bootstraps the app on mount: fetches initial REST state into the stores and
// opens the WebSocket. Called from +layout.svelte's onMount. Returns a cleanup
// function that closes the socket — Svelte's onMount uses the returned value
// as its destroy hook.

import { HubSocket } from '$lib/ws.js'
import { apiGet, apiPost, apiDelete } from '$lib/api.js'
import { lights, setLightsFromList, applyLightUpdate, optimisticLightPatch } from './lights.js'
import { sonos } from './sonos.js'
import { automation } from './automation.js'
import { connected, deviceStatus } from './connection.js'
import { showMusicSuggestion, showMusicAutoPlayed } from './music.js'
import { showModeSuggestion, dismissModeSuggestion } from './modeSuggestion.js'
import { showBrightnessSuggestion, dismissBrightnessSuggestion } from './brightnessSuggestion.js'
import { ambient } from './ambient.js'
import { camera } from './camera.js'
import { pipeline } from './pipeline.js'
import { dispatchGamedayMessage } from './gameday.js'
import { startWeatherPolling, stopWeatherPolling } from './weather.js'

/** @type {HubSocket | null} */
let socket = null

// Brief lock to prevent WebSocket mode_update from overwriting an optimistic
// update before the server confirms. Cleared after 2s or when a matching
// server confirmation arrives.
let modeUpdateLockUntil = 0
/** @type {boolean | null} */
let pendingOverride = null  // expected manual_override value from server

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
        dnd: {
          enabled: !!d.dnd_enabled,
          expiry_utc: d.dnd_expiry_utc ?? null,
          minutes_remaining: d.dnd_minutes_remaining ?? 0,
        },
      })
    })
    .catch(() => {})

  apiGet('/api/automation/pipeline')
    .then((data) => {
      const d = /** @type {any} */ (data)
      pipeline.set({ current: d.current, history: d.history || [] })
    })
    .catch(() => {})

  // Weather polls every 5 min — matches the backend NWS cache.
  startWeatherPolling()

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
          // Direction-aware lock: during the post-click window, accept the
          // server's confirmation (manual_override matches what the user
          // just chose) and discard contradicting messages as stale.
          if (Date.now() < modeUpdateLockUntil && pendingOverride !== null) {
            if (data.manual_override !== pendingOverride) {
              break
            }
            modeUpdateLockUntil = 0
            pendingOverride = null
          }
          automation.update((prev) => ({ ...prev, ...data }))
          break
        case 'dnd_update':
          automation.update((prev) => ({
            ...prev,
            dnd: {
              enabled: !!data.enabled,
              expiry_utc: data.expiry_utc ?? null,
              minutes_remaining: data.minutes_remaining ?? 0,
            },
          }))
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
        case 'brightness_suggestion':
          showBrightnessSuggestion(data)
          break
        case 'brightness_suggestion_dismissed':
          dismissBrightnessSuggestion()
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
        case 'gameday_state':
        case 'gameday_play':
        case 'gameday_celebration':
          dispatchGamedayMessage(type, data)
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
    stopWeatherPolling()
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
  if (action === 'volume' && typeof params.volume === 'number') {
    const volume = Math.max(0, Math.min(100, Math.round(params.volume)))
    sonos.update((prev) => ({ ...prev, volume }))
    params = { ...params, volume }
  }
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
  const wantOverride = mode !== 'auto'
  // Arm the direction-aware lock — only contradicting WS messages get
  // discarded; the server's confirmation passes through and replaces the
  // optimistic state with real values (notably the detected mode after Auto).
  pendingOverride = wantOverride
  modeUpdateLockUntil = Date.now() + 2000
  automation.update((prev) => ({
    ...prev,
    mode: wantOverride ? mode : prev.mode,
    manual_override: wantOverride,
  }))
  try {
    await apiPost('/api/automation/override', { mode })
  } catch (e) {
    modeUpdateLockUntil = 0
    pendingOverride = null
    console.error('Mode override failed:', e)
  }
}

/** @param {string} title */
export async function playFavorite(title) {
  await apiPost(`/api/sonos/favorites/${encodeURIComponent(title)}/play`)
}

/** @param {number} durationMinutes */
export async function enableDND(durationMinutes = 120) {
  await apiPost('/api/automation/dnd', { duration_minutes: durationMinutes })
}

export async function clearDND() {
  await apiDelete('/api/automation/dnd')
}
