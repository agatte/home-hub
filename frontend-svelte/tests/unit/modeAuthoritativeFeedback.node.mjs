import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createContext, runInContext } from 'node:vm'

const source = readFileSync(new URL('../../src/lib/stores/init.js', import.meta.url), 'utf8')
const extract = (startMarker, endMarker) => {
  const start = source.indexOf(startMarker)
  const end = source.indexOf(endMarker, start)
  assert.ok(start >= 0 && end > start, 'source function is present')
  return source.slice(start, end).replace(/^export /, '')
}
const modeCode = extract('export async function setManualMode(', '/** @param {string} title */')
const sonosCode = extract('export function sonosCommand(', '/** @param {string} sceneId */')

function modeHarness({ post, get } = {}) {
  const updates = []
  const calls = []
  const ctx = {
    apiPost: async (...args) => { calls.push(args); return post ? post(...args) : { status: 'ok' } },
    apiGet: get || (async () => ({ current_mode: 'gaming', manual_override: true })),
    automationStateFromStatus: x => x,
    automation: { set(x) { updates.push(x) }, update() { throw Error('mode must not be optimistic') } },
    console: { error() {} },
  }
  createContext(ctx)
  runInContext('let modeRequestPending = false; let modeUpdateEpoch = 0;\n' + modeCode + '\nthis.issueMode = setManualMode', ctx)
  return { ctx, updates, calls, issueMode: ctx.issueMode }
}

test('unauthenticated denied Mode request never patches effective state', async () => {
  const h = modeHarness({ post: async () => { throw Error('POST /api/automation/override failed: 401') } })
  assert.equal(await h.issueMode('relax'), 'denied')
  assert.equal(h.updates.length, 0)
  assert.equal(h.calls.length, 1)
})

test('successful Mode request displays only an authoritative REST snapshot', async () => {
  let resolvePost
  const waiting = new Promise(r => { resolvePost = r })
  const h = modeHarness({
    post: async () => waiting,
    get: async () => ({ current_mode: 'working', manual_override: true }),
  })
  const pending = h.issueMode('working')
  assert.equal(h.updates.length, 0)
  resolvePost({ status: 'ok' })
  assert.equal(await pending, 'acknowledged')
  assert.deepEqual(JSON.parse(JSON.stringify(h.updates)), [{ current_mode: 'working', manual_override: true }])
})

test('late REST status cannot overwrite a newer WebSocket mode update', async () => {
  let resolveGet, markGetStarted
  const pendingGet = new Promise(r => { resolveGet = r })
  const getStarted = new Promise(r => { markGetStarted = r })
  const h = modeHarness({ get: async () => { markGetStarted(); return pendingGet } })
  const action = h.issueMode('gaming')
  await getStarted
  runInContext('modeUpdateEpoch += 1', h.ctx)
  resolveGet({ current_mode: 'gaming', manual_override: true })
  assert.equal(await action, 'acknowledged')
  assert.equal(h.updates.length, 0)
})

test('overlapping Mode clicks never dispatch a second authority change', async () => {
  let resolvePost
  const h = modeHarness({ post: async () => new Promise(r => { resolvePost = r }) })
  const pending = h.issueMode('relax')
  assert.equal(await h.issueMode('gaming'), 'busy')
  assert.equal(h.calls.length, 1)
  resolvePost({ status: 'ok' })
  assert.equal(await pending, 'acknowledged')
})

test('Sonos volume uses the actual WebSocket sender without optimistic playback state', () => {
  const frames = []
  const ctx = {
    socket: { send: (type, data) => { frames.push([type, data]); return true } },
    sonos: { update() { throw Error('unconfirmed Sonos state mutation') } },
  }
  createContext(ctx)
  runInContext(sonosCode + '\nthis.sendSonos = sonosCommand', ctx)
  assert.equal(ctx.sendSonos('volume', { volume: 52.7 }), true)
  assert.deepEqual(JSON.parse(JSON.stringify(frames)), [['sonos_command', { action: 'volume', volume: 53 }]])
  ctx.socket = null
  assert.equal(ctx.sendSonos('pause'), false)
})

test('Mode deck presents accessible denied and uncertain command feedback', () => {
  const deck = readFileSync(new URL('../../src/lib/components/ModeCardDeck.svelte', import.meta.url), 'utf8')
  assert.match(deck, /outcome === 'denied'/)
  assert.match(deck, /outcome === 'uncertain'/)
  assert.match(deck, /role="status" aria-live="polite">\{modeFeedback\}/)
})
