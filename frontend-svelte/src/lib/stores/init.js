// Bootstraps the app on mount: fetches initial REST state into the stores and
// opens the WebSocket. Called from +layout.svelte's onMount. Returns a cleanup
// function that closes the socket — Svelte's onMount uses the returned value
// as its destroy hook.

import { validBrightnessSuggestion, validModeSuggestion } from '../quietAtlas/suggestionValidation.js'
import { receiveAmbientContext, resetAmbientContext } from '../quietAtlas/ambient.js'
import { HubSocket } from '$lib/ws.js'
import { apiGet, apiPost, apiDelete } from '$lib/api.js'
import { lights, setLightsFromList, applyLightUpdate } from './lights.js'
import { lightCommandTracker } from './lightCommandResults.js'
import { sonos, sonosLiveReport } from './sonos.js'
import { automation, automationStateFromStatus, mergeAutomationUpdate } from './automation.js'
import { connected, deviceStatus } from './connection.js'
import { showMusicSuggestion, showMusicAutoPlayed, dismissMusicSuggestion, musicAutoPlayed } from './music.js'
import { modeSuggestion, showModeSuggestion, dismissModeSuggestion } from './modeSuggestion.js'
import { brightnessSuggestion, showBrightnessSuggestion, dismissBrightnessSuggestion } from './brightnessSuggestion.js'
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

// Restore only a fresh, still-pending record matching the reported context.
// This read never grants command authority; all accept actions remain ID-scoped
// and the server rechecks pending status (and brightness context).
/** @param {any} result @param {{mode:string,time_period?:string}} context @param {Set<number>} invalidModeIds @param {Set<number>} invalidBrightnessIds */
function pendingSuggestionRows(result, context, invalidModeIds, invalidBrightnessIds) {
  const now = Date.now()
  const rows = Array.isArray(result?.suggestions) ? result.suggestions.filter(row => {
    const fired = Date.parse(row?.fired_at)
    return row?.status === 'pending' && Number.isSafeInteger(row.id) && row.id > 0 &&
      Number.isFinite(fired) && fired <= now && now - fired < 60 * 60 * 1000 &&
      row.current_mode_at_fire === context.mode &&
      Number.isInteger(row.confidence) && row.confidence >= 0 && row.confidence <= 100 &&
      Number.isSafeInteger(row.sample_count) && row.sample_count > 0
  }) : []
  const mode = rows.find(row => row.kind === 'mode' && !invalidModeIds.has(row.id) &&
    Number.isSafeInteger(row.rule_id) && row.rule_id > 0 &&
    ['relax','working','watching','gaming','cooking','social'].includes(row.predicted_mode))
  const brightness = rows.find(row => validBrightnessSuggestion(row) && !invalidBrightnessIds.has(row.id) &&
    row.payload.mode === context.mode && typeof context.time_period === 'string' &&
    row.payload.period === context.time_period)
  return {
    mode: mode ? {suggestion_id:mode.id,rule_id:mode.rule_id,predicted_mode:mode.predicted_mode,confidence:mode.confidence,sample_count:mode.sample_count,message:''} : null,
    brightness: brightness ?? null,
  }
}

export function initStores() {
  let connectionEpoch = 0
  let socketConnected = false
  let restored = false
  let modeEvents = 0
  let brightnessEvents = 0
  let liveContextKey = ''
  /** @type {{house_state?:string,mode?:string,time_period?:string}} */
  let liveContext = {}
  let contextEpoch = 0
  /** @type {Set<number>} */
  const invalidModeIds = new Set()
  /** @type {Set<number>} */
  const invalidBrightnessIds = new Set()

  /** @param {any} data */
  function restorePendingSuggestions(data) {
    if (!socketConnected || !data || typeof data !== 'object') return
    // Partial mode_update frames must not inherit REST or optimistic context.
    const next = {...liveContext}
    if (Object.hasOwn(data,'house_state')) next.house_state = typeof data.house_state === 'string' ? data.house_state : undefined
    if (Object.hasOwn(data,'mode')) next.mode = typeof data.mode === 'string' ? data.mode : undefined
    if (Object.hasOwn(data,'time_period')) next.time_period = typeof data.time_period === 'string' ? data.time_period : undefined
    liveContext = next
    const key = JSON.stringify([next.house_state,next.mode,next.time_period])
    if (liveContextKey !== key) {
      liveContextKey = key
      contextEpoch += 1
      restored = false
      modeEvents = 0
      brightnessEvents = 0
      // A card belongs to the live context in which it was received.
      // Do not revive an invalidated ID if the context later cycles back.
      modeSuggestion.update(current => { if (current) invalidModeIds.add(current.suggestion_id); return null })
      brightnessSuggestion.update(current => { if (current) invalidBrightnessIds.add(current.id); return null })
      dismissMusicSuggestion()
    }
    if (restored || !['home','winding_down'].includes(next.house_state ?? '') || !next.mode) return
    restored = true
    const connection = connectionEpoch
    const context = contextEpoch
    const observed = {mode:next.mode,time_period:next.time_period}
    apiGet('/api/rules/suggestions?status=pending&limit=20')
      .then(result => {
        if (!socketConnected || connectionEpoch !== connection || contextEpoch !== context) return
        const rows = pendingSuggestionRows(result,observed,invalidModeIds,invalidBrightnessIds)
        if (modeEvents === 0 && rows.mode && !invalidModeIds.has(rows.mode.suggestion_id)) modeSuggestion.update(current => current ?? rows.mode)
        if (brightnessEvents === 0 && rows.brightness && !invalidBrightnessIds.has(rows.brightness.id)) brightnessSuggestion.update(current => current ?? rows.brightness)
      })
      .catch(() => {})
  }

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
          restorePendingSuggestions(data)
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
          modeEvents += 1
          if (socketConnected && ['home','winding_down'].includes(liveContext.house_state ?? '') && liveContext.mode && validModeSuggestion(data) && !invalidModeIds.has(data.suggestion_id)) showModeSuggestion(data)
          break
        case 'mode_suggestion_dismissed':
          modeEvents += 1
          if (Number.isSafeInteger(data?.id)) {
            invalidModeIds.add(data.id)
            modeSuggestion.update(current => current?.suggestion_id === data.id ? null : current)
          }
          else if (data?.id == null) dismissModeSuggestion()
          break
        case 'brightness_suggestion':
          brightnessEvents += 1
          if (socketConnected && ['home','winding_down'].includes(liveContext.house_state ?? '') && validBrightnessSuggestion(data) && data.payload.mode === liveContext.mode && data.payload.period === liveContext.time_period && !invalidBrightnessIds.has(data.id)) showBrightnessSuggestion(data)
          break
        case 'brightness_suggestion_dismissed':
          brightnessEvents += 1
          if (Number.isSafeInteger(data?.id)) {
            invalidBrightnessIds.add(data.id)
            brightnessSuggestion.update(current => current?.id === data.id ? null : current)
          }
          else if (data?.id == null) dismissBrightnessSuggestion()
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
      connectionEpoch += 1
      socketConnected = isConnected
      restored = false
      modeEvents = 0
      brightnessEvents = 0
      liveContextKey = ''
      liveContext = {}
      invalidModeIds.clear()
      invalidBrightnessIds.clear()
      contextEpoch += 1
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
    connectionEpoch += 1
    socketConnected = false
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
