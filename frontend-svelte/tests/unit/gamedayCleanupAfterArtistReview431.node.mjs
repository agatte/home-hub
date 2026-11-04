import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'

// Execute the real exported REST-prime function with synthetic, mocked globals.
// The module itself imports Svelte/runtime dependencies unavailable in Sandbox.
const source = readFileSync(new URL('../../src/lib/stores/gameday.js', import.meta.url), 'utf8')
const marker = 'export async function fetchGamedayInitial(generation = feedGeneration) {'
const start = source.indexOf(marker)
assert.ok(start >= 0, 'expected real function source')
const functionBody = source.slice(start).replace(/^export /, '')

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
function harness(reply) {
  const calls = []
  let state = { viewerSyncLoaded: false, scheduleLoaded: false, schedule: [] }
  const context = {
    feedGeneration: 1,
    stateRevision: 0,
    viewerAuthorityRevision: 0,
    apiGet: (path) => { calls.push(path); return reply(path) },
    gameday: { update: (update) => { state = update(state) } },
  }
  runInNewContext(functionBody + '\nthis.run = fetchGamedayInitial;', context, { timeout: 1000 })
  return {
    calls,
    run: () => context.run(1),
    stop: () => { context.feedGeneration++ },
    get state() { return state },
  }
}

test('direct cleanup before a stale fetch starts makes no API requests', async () => {
  const h = harness(() => { throw Error('no request expected') })
  h.stop()
  await h.run()
  assert.deepEqual(h.calls, [])
})

test('viewer-sync rejection after route cleanup cannot start state or schedule', async () => {
  const pending = deferred()
  const h = harness(() => pending.promise)
  const running = h.run()
  assert.deepEqual(h.calls, ['/api/gameday/viewer-sync'])
  h.stop()
  pending.reject(Error('synthetic viewer-sync failure'))
  await running
  assert.deepEqual(h.calls, ['/api/gameday/viewer-sync'])
  assert.equal(h.state.viewerSyncLoaded, false)
})

test('state rejection after route cleanup cannot start schedule', async () => {
  const pending = deferred()
  const h = harness(path => path.endsWith('/viewer-sync')
    ? Promise.resolve({ viewer_state: null })
    : pending.promise)
  const running = h.run()
  await new Promise(setImmediate)
  assert.deepEqual(h.calls, ['/api/gameday/viewer-sync', '/api/gameday/state'])
  h.stop()
  pending.reject(Error('synthetic state failure'))
  await running
  assert.equal(h.calls.length, 2)
  assert.equal(h.state.scheduleLoaded, false)
})

test('schedule rejection after route cleanup cannot update stale store', async () => {
  const pending = deferred()
  const h = harness(path => path.endsWith('/schedule')
    ? pending.promise : Promise.resolve({ status: 'no-game' }))
  const running = h.run()
  await new Promise(setImmediate)
  assert.deepEqual(h.calls, [
    '/api/gameday/viewer-sync', '/api/gameday/state', '/api/gameday/schedule',
  ])
  h.stop()
  pending.reject(Error('synthetic schedule failure'))
  await running
  assert.equal(h.state.scheduleLoaded, false)
})

test('owned feed still primes three endpoints and stores schedule', async () => {
  const h = harness(path => path.endsWith('/schedule')
    ? Promise.resolve([{ id: 'synthetic-game' }])
    : Promise.resolve({ status: 'no-game' }))
  await h.run()
  assert.deepEqual(h.calls, [
    '/api/gameday/viewer-sync', '/api/gameday/state', '/api/gameday/schedule',
  ])
  assert.equal(h.state.viewerSyncLoaded, true)
  assert.equal(h.state.scheduleLoaded, true)
  assert.equal(h.state.schedule.length, 1)
})
