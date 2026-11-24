// Bootstraps the app on mount: fetches initial REST state into the stores and
// opens the WebSocket. Called from +layout.svelte's onMount. Returns a cleanup
// function that closes the socket — Svelte's onMount uses the returned value
// as its destroy hook.

import { receiveAmbientContext, resetAmbientContext } from '../quietAtlas/ambient.js'
import { HubSocket } from '$lib/ws.js'
import { apiGet, apiPost, apiDelete } from '$lib/api.js'
import { lights, setLightsFromList, applyLightUpdate } from './lights.js'
import { lightCommandTracker } from './lightCommandResults.js'
import { sonos, sonosLiveReport } from './sonos.js'
import { automation, automationStateFromStatus, mergeAutomationUpdate } from './automation.js'
import { connected, deviceStatus } from './connection.js'
import { showMusicSuggestion, showMusicAutoPlayed, dismissMusicSuggestion, musicAutoPlayed } from './music.js'
import { showModeSuggestion, dismissModeSuggestion } from './modeSuggestion.js'
import { showBrightnessSuggestion, dismissBrightnessSuggestion } from './brightnessSuggestion.js'
import { ambient } from './ambient.js'
import { camera } from './camera.js'
import { pipeline } from './pipeline.js'
import { startWeatherPolling, stopWeatherPolling } from './weather.js'

/** @type {HubSocket | null} */
let socket = null

// The server is the sole source of displayed mode authority. A single-flight
// manual request prevents out-of-order user writes; a version check prevents a
// delayed REST snapshot from overwriting a newer WebSocket mode update.
let modeRequestPending = false
let modeUpdateEpoch = 0

function resetSuggestions() {
  dismissModeSuggestion()
  dismissBrightnessSuggestion()
  dismissMusicSuggestion()
  musicAutoPlayed.set(null)
}

export function initStores() {
  resetSuggestions()
  sonosLiveReport.set(null)
  resetAmbientContext()
  lightCommandTracker.reset()
  deviceStatus.update((prev) => ({ ...prev, light_command_results: false }))
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

  const initialModeEpoch = modeUpdateEpoch
  apiGet('/api/automation/status')
    .then((data) => {
      if (modeUpdateEpoch === initialModeEpoch && data) {
        modeUpdateEpoch += 1
        automation.set(automationStateFromStatus(/** @type {any} */ (data)))
      }
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
          sonosLiveReport.set(data)
          sonos.set(data)
          break
        case 'connection_status':
          deviceStatus.set(data)
          lightCommandTracker.setCapability(data?.light_command_results === true)
          break
        case 'light_command_result':
          lightCommandTracker.receive(data)
          break
        case 'mode_update':
          // Never suppress physical/automation owner updates to protect a
          // speculative client choice. A newer live update wins over REST.
          modeUpdateEpoch += 1
          receiveAmbientContext(data)
          automation.update((prev) => mergeAutomationUpdate(prev, data))
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
        default:
          console.warn('[ws] Unknown message type:', type, data)
          break
      }
    },
    (isConnected) => {
      resetSuggestions()
      sonosLiveReport.set(null)
      resetAmbientContext()
      connected.set(isConnected)
      if (!isConnected) {
        lightCommandTracker.disconnect()
        deviceStatus.update((prev) => ({ ...prev, light_command_results: false }))
      }
    }
  )
  socket.connect()

  return () => {
    resetSuggestions()
    sonosLiveReport.set(null)
    resetAmbientContext()
    lightCommandTracker.reset()
    socket?.close()
    socket = null
    stopWeatherPolling()
  }
}

// ---------- Action helpers (parity with HubContext actions) ----------

/**
 * Send one guarded fixture command without predicting device state.
 * @param {string} lightId
 * @param {Record<string, unknown>} state
 * @param {{ optimistic?: boolean }} [options]
 */
export function setLight(lightId, state, options = {}) {
  lightCommandTracker.submit(lightId, state, (data) =>
    socket?.send('light_command', data) === true,
  )
}

/**
 * @param {string} action
 * @param {Record<string, unknown>} [params]
 */
export function sonosCommand(action, params = {}) {
  if (action === 'volume' && typeof params.volume === 'number') {
    const volume = Math.max(0, Math.min(100, Math.round(params.volume)))
    params = { ...params, volume }
  }
  // A sent WS frame is not Sonos ACK. Only an actual sonos_update may change
  // the reported volume or playback state, including after session expiry.
  return socket?.send('sonos_command', { action, ...params }) === true
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
  if (modeRequestPending) return 'busy'
  modeRequestPending = true
  try {
    const outcome = await apiPost('/api/automation/override', { mode })
    if (outcome?.status !== 'ok') return 'uncertain'
    // A successful HTTP response acknowledges server handling, not the
    // displayed effective mode. Re-read authority; discard a delayed snapshot
    // if a newer live mode_update arrived while this fetch was pending.
    const observedEpoch = modeUpdateEpoch
    try {
      const state = await apiGet('/api/automation/status')
      if (state && modeUpdateEpoch === observedEpoch) {
        modeUpdateEpoch += 1
        automation.set(automationStateFromStatus(state))
      }
    } catch { /* Keep last reported state; live WebSocket remains authority. */ }
    return 'acknowledged'
  } catch (e) {
    console.error('Mode override not confirmed:', e)
    return /failed: 40[13]\b/.test(e instanceof Error ? e.message : String(e)) ? 'denied' : 'uncertain'
  } finally {
    modeRequestPending = false
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
