import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'

const source = readFileSync(new URL('../../src/lib/stores/init.js', import.meta.url), 'utf8')
  .replace(/^import .*$/gm, '').replace(/export /g, '')
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return { promise, resolve, reject } }
const store = value => ({ value, set(v) { this.value = v }, update(f) { this.value = f(this.value) } })
function setup() {
  const automation = store({ mode: 'home', manual_override: false }), sonos = store({ volume: 20 })
  const initial = deferred(), initialSonos = deferred(), posts = [], gets = [], sends = []
  const sonosLiveReport = store(null)
  const modeSuggestion = store(null), brightnessSuggestion = store(null)
  let ws, sendOK = true
  class HubSocket { constructor(onMessage, onConnection) { ws = { onMessage, onConnection } } connect() {} close() {} send(type, data) { sends.push({ type, data }); return sendOK } }
  const noop = () => {}, dummy = store({})
  const ctx = { HubSocket, automation, sonos, sonosLiveReport, console: { error: noop, warn: noop },
    apiGet: path => { if (path === '/api/sonos/status') return initialSonos.promise; if (path === '/api/automation/status') { const d = gets.length ? deferred() : initial; gets.push(d); return d.promise } return Promise.resolve({}) },
    apiPost: () => { const d = deferred(); posts.push(d); return d.promise }, apiDelete: noop,
    automationStateFromStatus: x => ({ mode: x.current_mode, manual_override: x.manual_override }),
    mergeAutomationUpdate: (prev, data) => ({ ...prev, ...data }),
    lightCommandTracker: { reset: noop, disconnect: noop, setCapability: noop, receive: noop },
    deviceStatus: dummy, connected: dummy, ambient: dummy, camera: dummy, pipeline: dummy,
    receiveAmbientContext: noop, resetAmbientContext: noop, modeSuggestion, brightnessSuggestion, showModeSuggestion: v => modeSuggestion.set(v), showBrightnessSuggestion: v => brightnessSuggestion.set(v), dismissModeSuggestion: () => modeSuggestion.set(null), dismissBrightnessSuggestion: () => brightnessSuggestion.set(null), dismissMusicSuggestion: noop, musicAutoPlayed: {set: noop}, setLightsFromList: noop, applyLightUpdate: noop,
    startWeatherPolling: noop, stopWeatherPolling: noop }
  const api = runInNewContext(`${source}\n;({initStores, setManualMode, sonosCommand})`, ctx)
  api.initStores()
  return { ...api, automation, sonos, sonosLiveReport, modeSuggestion, brightnessSuggestion, initialSonos, initial, posts, gets, sends, ws, setSendOK: v => { sendOK = v } }
}
const tick = () => new Promise(resolve => setImmediate(resolve))

test('denied, expired and timed out mode requests never predict success', async () => {
  const h = setup()
  for (const [message, expected] of [['POST /api/automation/override failed: 401', 'denied'], ['POST /api/automation/override failed: 403', 'denied'], ['timeout', 'uncertain']]) {
    const request = h.setManualMode('gaming')
    assert.equal(h.automation.value.mode, 'home')
    h.posts.at(-1).reject(new Error(message))
    assert.equal(await request, expected)
    assert.equal(h.automation.value.mode, 'home')
  }
})

test('acknowledgement reconciles, serializes, and newer WS beats delayed snapshots', async () => {
  const h = setup()
  const request = h.setManualMode('gaming')
  assert.equal(await h.setManualMode('relax'), 'busy')
  h.posts[0].resolve({ status: 'ok' }); await tick()
  h.ws.onMessage({ type: 'mode_update', data: { mode: 'watching', manual_override: false } })
  h.gets[1].resolve({ current_mode: 'gaming', manual_override: true })
  assert.equal(await request, 'acknowledged')
  h.initial.resolve({ current_mode: 'idle', manual_override: false }); await tick()
  assert.equal(h.automation.value.mode, 'watching')
  const next = h.setManualMode('relax'); h.posts[1].resolve({ status: 'ok' }); await tick()
  h.gets[2].resolve({ current_mode: 'relax', manual_override: true })
  assert.equal(await next, 'acknowledged')
  assert.equal(h.automation.value.mode, 'relax')
})

test('Sonos send and failure never patch volume; server update is authoritative', () => {
  const h = setup()
  assert.equal(h.sonosCommand('volume', { volume: 150 }), true)
  assert.equal(h.sends[0].data.volume, 100)
  assert.equal(h.sonos.value.volume, 20)
  h.setSendOK(false)
  assert.equal(h.sonosCommand('volume', { volume: 30 }), false)
  assert.equal(h.sonos.value.volume, 20)
  h.ws.onMessage({ type: 'sonos_update', data: { volume: 35 } })
  assert.equal(h.sonos.value.volume, 35)
})

test('Music live report is isolated from late startup reads, sends and connection changes', async () => {
  const h = setup()
  assert.equal(h.sonosLiveReport.value, null)
  h.ws.onConnection(true)
  h.ws.onMessage({ type: 'sonos_update', data: { volume: 35 } })
  assert.equal(h.sonosLiveReport.value.volume, 35)
  h.initialSonos.resolve({ volume: 12 }); await tick()
  assert.equal(h.sonos.value.volume, 12)
  assert.equal(h.sonosLiveReport.value.volume, 35)
  h.sonosCommand('volume', { volume: 60 })
  assert.equal(h.sonosLiveReport.value.volume, 35)
  h.ws.onConnection(false)
  assert.equal(h.sonosLiveReport.value, null)
  h.ws.onConnection(true)
  assert.equal(h.sonosLiveReport.value, null)
  h.ws.onMessage({ type: 'sonos_update', data: { volume: 42 } })
  assert.equal(h.sonosLiveReport.value.volume, 42)
})

test('ID-specific dismissals preserve newer suggestions and reconnect invalidates cache', () => {
  const h = setup()
  h.ws.onConnection(true)
  h.ws.onMessage({type:'mode_suggestion',data:{suggestion_id:18}})
  h.ws.onMessage({type:'brightness_suggestion',data:{id:20}})
  h.ws.onMessage({type:'mode_suggestion_dismissed',data:{id:17}})
  h.ws.onMessage({type:'brightness_suggestion_dismissed',data:{id:19}})
  assert.equal(h.modeSuggestion.value.suggestion_id,18)
  assert.equal(h.brightnessSuggestion.value.id,20)
  h.ws.onMessage({type:'mode_suggestion_dismissed',data:{id:18}})
  assert.equal(h.modeSuggestion.value,null)
  h.ws.onConnection(false)
  assert.equal(h.brightnessSuggestion.value,null)
  h.ws.onConnection(true)
  assert.equal(h.modeSuggestion.value,null)
})
