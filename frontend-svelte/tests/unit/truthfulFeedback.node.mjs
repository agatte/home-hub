import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import { validBrightnessSuggestion, validModeSuggestion } from '../../src/lib/quietAtlas/suggestionValidation.js'

const source = readFileSync(new URL('../../src/lib/stores/init.js', import.meta.url), 'utf8')
  .replace(/^import .*$/gm, '').replace(/export /g, '')
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return { promise, resolve, reject } }
const store = value => ({ value, set(v) { this.value = v }, update(f) { this.value = f(this.value) } })
function setup() {
  const automation = store({ mode: 'home', manual_override: false }), sonos = store({ volume: 20 })
  const initial = deferred(), initialSonos = deferred(), posts = [], gets = [], sends = [], pendingReads = []
  const sonosLiveReport = store(null)
  const modeSuggestion = store(null), brightnessSuggestion = store(null)
  let ws, sendOK = true
  class HubSocket { constructor(onMessage, onConnection) { ws = { onMessage, onConnection } } connect() {} close() {} send(type, data) { sends.push({ type, data }); return sendOK } }
  const noop = () => {}, dummy = store({})
  const ctx = { validBrightnessSuggestion, validModeSuggestion, HubSocket, automation, sonos, sonosLiveReport, console: { error: noop, warn: noop },
    apiGet: path => { if (path === '/api/rules/suggestions?status=pending&limit=20') { const d=deferred(); pendingReads.push(d); return d.promise } if (path === '/api/sonos/status') return initialSonos.promise; if (path === '/api/automation/status') { const d = gets.length ? deferred() : initial; gets.push(d); return d.promise } return Promise.resolve({}) },
    apiPost: () => { const d = deferred(); posts.push(d); return d.promise }, apiDelete: noop,
    automationStateFromStatus: x => ({ mode: x.current_mode, manual_override: x.manual_override }),
    mergeAutomationUpdate: (prev, data) => ({ ...prev, ...data }),
    lightCommandTracker: { reset: noop, disconnect: noop, setCapability: noop, receive: noop },
    deviceStatus: dummy, connected: dummy, ambient: dummy, camera: dummy, pipeline: dummy,
    receiveAmbientContext: noop, resetAmbientContext: noop, modeSuggestion, brightnessSuggestion, showModeSuggestion: v => modeSuggestion.set(v), showBrightnessSuggestion: v => brightnessSuggestion.set(v), dismissModeSuggestion: () => modeSuggestion.set(null), dismissBrightnessSuggestion: () => brightnessSuggestion.set(null), dismissMusicSuggestion: noop, musicAutoPlayed: {set: noop}, setLightsFromList: noop, applyLightUpdate: noop,
    startWeatherPolling: noop, stopWeatherPolling: noop }
  const api = runInNewContext(`${source}\n;({initStores, setManualMode, sonosCommand})`, ctx)
  const destroy=api.initStores()
  return { ...api,destroy,pendingReads, automation, sonos, sonosLiveReport, modeSuggestion, brightnessSuggestion, initialSonos, initial, posts, gets, sends, ws, setSendOK: v => { sendOK = v } }
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
  h.ws.onConnection(true);live(h)
  h.ws.onMessage({type:'mode_suggestion',data:modeEvent(18)})
  h.ws.onMessage({type:'brightness_suggestion',data:brightnessEvent(20)})
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

test('older brightness resolution cannot clear a newer suggestion', () => {
  const h=setup();h.ws.onConnection(true);live(h)
  h.ws.onMessage({type:'brightness_suggestion',data:brightnessEvent(18)})
  h.ws.onMessage({type:'brightness_suggestion_dismissed',data:{id:17}})
  assert.equal(h.brightnessSuggestion.value.id,18)
  h.ws.onMessage({type:'brightness_suggestion_dismissed',data:{id:18}})
  assert.equal(h.brightnessSuggestion.value,null)
})

const live = (h, mode='working', house_state='home') => h.ws.onMessage({type:'mode_update',data:{house_state,mode,time_period:'day'}})
const modeEvent = id => ({suggestion_id:id,rule_id:4,predicted_mode:'gaming',confidence:85,sample_count:9,message:''})
const brightnessEvent = id => ({id,kind:'brightness',confidence:70,sample_count:8,payload:{mode:'working',period:'day',weather_class:'clear',light_id:'1',suggested_bri:120,sample_count:8}})
const pendingRows = () => ({suggestions:[
  {id:71,kind:'mode',status:'pending',rule_id:4,predicted_mode:'gaming',current_mode_at_fire:'working',confidence:85,sample_count:9,fired_at:new Date().toISOString()},
  {id:72,kind:'brightness',status:'pending',current_mode_at_fire:'working',confidence:70,sample_count:8,fired_at:new Date().toISOString(),payload:{mode:'working',period:'day',weather_class:'clear',light_id:'1',suggested_bri:120,sample_count:8}}
]})

test('fresh pending suggestions restore only after a live awake report; no action sent', async()=>{
  const h=setup()
  h.ws.onConnection(true)
  assert.equal(h.pendingReads.length,0)
  live(h,'working','sleeping')
  assert.equal(h.pendingReads.length,0)
  live(h)
  assert.equal(h.pendingReads.length,1)
  live(h)
  assert.equal(h.pendingReads.length,1)
  h.pendingReads[0].resolve(pendingRows());await tick()
  assert.equal(h.modeSuggestion.value.suggestion_id,71)
  assert.equal(h.brightnessSuggestion.value.id,72)
  assert.equal(h.posts.length,0)
})

test('pending read never overwrites later events or resurrects dismissed cards', async()=>{
  const h=setup()
  h.ws.onConnection(true);live(h)
  h.ws.onMessage({type:'mode_suggestion',data:modeEvent(90)})
  h.ws.onMessage({type:'brightness_suggestion_dismissed',data:{id:72}})
  h.pendingReads[0].resolve(pendingRows());await tick()
  assert.equal(h.modeSuggestion.value.suggestion_id,90)
  assert.equal(h.brightnessSuggestion.value,null)
})

test('connection, context and cleanup fence delayed pending reads', async()=>{
  const h=setup()
  h.ws.onConnection(true);live(h)
  h.ws.onConnection(false);h.ws.onConnection(true);live(h)
  h.pendingReads[0].resolve(pendingRows());await tick()
  assert.equal(h.modeSuggestion.value,null)
  live(h,'gaming')
  h.pendingReads[1].resolve(pendingRows());await tick()
  assert.equal(h.brightnessSuggestion.value,null)
  h.ws.onConnection(false);h.ws.onConnection(true);live(h)
  h.destroy()
  h.pendingReads[2].resolve(pendingRows());h.pendingReads[3].resolve(pendingRows());await tick()
  assert.equal(h.modeSuggestion.value,null)
})

test('expired or mismatched pending records are not restored', async()=>{
  const h=setup()
  h.ws.onConnection(true);live(h)
  const rows=pendingRows()
  rows.suggestions[0].fired_at=new Date(Date.now()-61*60*1000).toISOString()
  rows.suggestions[1].payload.period='night'
  h.pendingReads[0].resolve(rows);await tick()
  assert.equal(h.modeSuggestion.value,null)
  assert.equal(h.brightnessSuggestion.value,null)
})

test('new context starts a replacement read, invalidates cards and ignores old responses',async()=>{
  const h=setup();h.ws.onConnection(true);live(h)
  live(h,'gaming')
  assert.equal(h.pendingReads.length,2)
  h.pendingReads[0].resolve(pendingRows());await tick()
  assert.equal(h.modeSuggestion.value,null)
  const next=pendingRows()
  next.suggestions[0]={...next.suggestions[0],id:81,current_mode_at_fire:'gaming',predicted_mode:'working'}
  next.suggestions[1]={...next.suggestions[1],id:82,current_mode_at_fire:'gaming',payload:{...next.suggestions[1].payload,mode:'gaming'}}
  h.pendingReads[1].resolve(next);await tick()
  assert.equal(h.modeSuggestion.value.suggestion_id,81)
  assert.equal(h.brightnessSuggestion.value.id,82)
  h.ws.onMessage({type:'mode_update',data:{mode:'watching'}})
  assert.equal(h.modeSuggestion.value,null)
  assert.equal(h.brightnessSuggestion.value,null)
  assert.equal(h.pendingReads.length,3)
})

test('malformed live and pending brightness rows never become actionable',async()=>{
  const h=setup();h.ws.onConnection(true);live(h)
  h.ws.onMessage({type:'brightness_suggestion',data:{...brightnessEvent(99),payload:{mode:'working',period:'day'}}})
  assert.equal(h.brightnessSuggestion.value,null)
  h.ws.onConnection(false);h.ws.onConnection(true);live(h)
  const rows=pendingRows()
  rows.suggestions[1].payload.light_targets={'1':120,'999':100}
  h.pendingReads[1].resolve(rows);await tick()
  assert.equal(h.brightnessSuggestion.value,null)
})

test('context cycle skips invalidated IDs and restores later eligible pending rows',async()=>{
  const h=setup();h.ws.onConnection(true);live(h)
  h.pendingReads[0].resolve(pendingRows());await tick()
  assert.equal(h.modeSuggestion.value.suggestion_id,71)
  assert.equal(h.brightnessSuggestion.value.id,72)
  live(h,'gaming');live(h)
  const rows=pendingRows()
  rows.suggestions.push({...rows.suggestions[0],id:61},{...rows.suggestions[1],id:62})
  h.pendingReads[1].resolve(pendingRows());h.pendingReads[2].resolve(rows);await tick()
  assert.equal(h.modeSuggestion.value.suggestion_id,61)
  assert.equal(h.brightnessSuggestion.value.id,62)
  assert.equal(h.posts.length,0)
})
