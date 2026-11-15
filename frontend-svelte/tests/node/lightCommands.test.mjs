import test from 'node:test'
import assert from 'node:assert/strict'
import { createLightCommands } from '../../src/lib/stores/lightCommands.js'

const observation = { light_id: '2', reachable: true, on: true, bri: 80 }
const tick = () => new Promise((resolve) => setImmediate(resolve))
function fixture(options = {}) {
  const writes = [], applied = [], reports = [], timers = new Map()
  let timer = 0
  const commands = createLightCommands({
    send: (data) => { writes.push(data); return true },
    read: async () => observation,
    apply: (light) => applied.push(light),
    report: (id, status) => reports.push({ id, status }),
    uuid: () => 'synthetic_session_12345678',
    schedule: (fn) => { timers.set(++timer, fn); return timer },
    cancel: (id) => timers.delete(id),
    ...options,
  })
  commands.connection(true)
  return { commands, writes, applied, reports, timers }
}
for (const status of ['denied', 'unavailable', 'uncertain', 'invalid', 'unexpected']) {
  test(`${status} restores unchanged authoritative state without optimistic off`, async () => {
    const f = fixture()
    f.commands.observe(observation)
    f.commands.set('2', { on: false })
    assert.deepEqual(f.applied, [observation])
    f.commands.result({ command_id: f.writes[0].command_id, status })
    await tick()
    assert.deepEqual(f.applied, [observation, observation])
    assert.equal(f.writes.length, 1)
    assert.deepEqual(f.reports, [{ id: '2', status }])
    assert.equal(f.timers.size, 0)
  })
}
test('ACK never patches requested state or claims physical completion', () => {
  const f = fixture()
  f.commands.set('2', { on: false })
  f.commands.result({ ...f.writes[0], status: 'acknowledged' })
  assert.deepEqual(f.applied, [])
  assert.deepEqual(f.reports, [])
  assert.equal(f.timers.size, 0)
})
test('latest drag receipt wins; IDs stay unique across fixtures and reconnects', async () => {
  const f = fixture()
  for (let i = 0; i < 50; i++) f.commands.set('2', { bri: i + 1 })
  f.commands.set('3', { bri: 10 })
  f.commands.result({ ...f.writes[0], status: 'denied' })
  await tick()
  assert.deepEqual(f.applied, [])
  assert.equal(f.timers.size, 2)
  f.commands.connection(false)
  assert.equal(f.timers.size, 0)
  f.commands.connection(true)
  f.commands.set('2', { bri: 100 })
  assert.equal(new Set(f.writes.map((w) => w.command_id)).size, 52)
  assert.ok(f.writes.every((w) => /^[A-Za-z0-9_-]{8,64}$/.test(w.command_id)))
})
test('timeout reads but never retries the physical command', async () => {
  const f = fixture()
  f.commands.set('2', { on: false })
  const timeout = [...f.timers.values()][0]
  timeout()
  await tick()
  assert.deepEqual(f.applied, [observation])
  assert.equal(f.writes.length, 1)
})
for (const boundary of ['command', 'observation', 'disconnect', 'close']) {
  test(`late reconciliation cannot overwrite a newer ${boundary}`, async () => {
    let resolve
    const f = fixture({ read: () => new Promise((done) => { resolve = done }) })
    f.commands.set('2', { on: false })
    f.commands.result({ ...f.writes[0], status: 'denied' })
    if (boundary === 'command') f.commands.set('2', { bri: 40 })
    if (boundary === 'observation') f.commands.observe({ ...observation, bri: 42 })
    if (boundary === 'disconnect') f.commands.connection(false)
    if (boundary === 'close') f.commands.close()
    resolve(observation)
    await tick()
    assert.deepEqual(f.applied, boundary === 'observation' ? [{ ...observation, bri: 42 }] : [])
  })
}
test('failed read and disconnected send retain observations, reconnect reads only', async () => {
  let reads = 0
  const f = fixture({ read: async () => { reads++; throw Error('offline') } })
  f.commands.observe(observation)
  f.commands.set('2', { on: false })
  f.commands.result({ ...f.writes[0], status: 'uncertain' })
  await tick()
  f.commands.connection(false)
  f.commands.set('2', { on: false })
  f.commands.connection(true)
  await tick()
  assert.equal(reads, 2)
  assert.equal(f.writes.length, 1)
  assert.deepEqual(f.applied, [observation])
})
test('wrong fixture, unreachable reads and foreign receipts cannot patch state', async () => {
  const f = fixture({ read: async () => ({ ...observation, light_id: '3' }) })
  f.commands.set('2', { on: false })
  f.commands.result({ ...f.writes[0], light_id: '3', status: 'denied' })
  f.commands.result({ command_id: 'foreign_id', status: 'denied' })
  assert.equal(f.timers.size, 1)
  f.commands.result({ ...f.writes[0], status: 'denied' })
  await tick()
  assert.deepEqual(f.applied, [])
  const unreachable = fixture({ read: async () => ({ ...observation, reachable: false }) })
  unreachable.commands.set('2', { on: false })
  unreachable.commands.result({ ...unreachable.writes[0], status: 'denied' })
  await tick()
  assert.deepEqual(unreachable.applied, [])
})
test('failed or throwing transport reconciles without an automatic retry', async () => {
  for (const send of [() => false, () => { throw Error('closed') }]) {
    const f = fixture({ send })
    f.commands.set('2', { on: false })
    await tick()
    assert.equal(f.timers.size, 0)
    assert.deepEqual(f.applied, [observation])
  }
})
test('independent client sessions have distinct correlation namespaces', () => {
  const a = fixture({ uuid: () => 'session_a_12345678' })
  const b = fixture({ uuid: () => 'session_b_12345678' })
  a.commands.set('2', { on: false }); b.commands.set('2', { on: false })
  assert.notEqual(a.writes[0].command_id, b.writes[0].command_id)
})

test('typed rejected readback 80 cannot overwrite newer 140 telemetry across commands and lights', async () => {
  let resolve
  const f = fixture({ read: () => new Promise(done => { resolve = done }) })
  f.commands.set('2', { bri:90 })
  const old = f.writes[0]
  f.commands.result({ ...old, status:'denied' })
  f.commands.set('2', { bri:140 })
  f.commands.set('3', { bri:60 })
  f.commands.observe({ ...observation, bri:140 })
  f.commands.reconciliation({ command_id:old.command_id, light_id:'2', observation })
  resolve(observation)
  await tick()
  assert.deepEqual(f.applied.map(x => x.bri), [140])
  assert.equal(f.timers.size, 2)
})
test('legacy advisory triggers a fresh fenced read without applying its stale payload', async () => {
  let resolve
  const f = fixture({ read: () => new Promise(done => { resolve = done }) })
  f.commands.reconciliation({ command_id:null, light_id:'2', observation })
  f.commands.observe({ ...observation, bri:140 })
  resolve(observation)
  await tick()
  assert.deepEqual(f.applied.map(x => x.bri), [140])
})

test('another light observation does not discard this light fenced reconciliation', async () => {
  let resolve
  const f = fixture({ read: () => new Promise(done => { resolve = done }) })
  f.commands.set('2', { on:false })
  f.commands.result({ ...f.writes[0], status:'denied' })
  f.commands.observe({ ...observation, light_id:'3', bri:140 })
  resolve(observation)
  await tick()
  assert.deepEqual(f.applied.map(x => [x.light_id,x.bri]), [['3',140],['2',80]])
})

// Run the actual store wiring with synthetic transport and disposable timers.
// This exercises the overlap between A's receipt tracker and B's reconciliation.
test('combined Home store wiring correlates denial, fences readback, and never replays', async () => {
  const { readFileSync } = await import('node:fs')
  const { default: vm } = await import('node:vm')
  const { createLightCommandReceiptTracker } = await import('../../src/lib/quietAtlas/lightCommandReceiptTracker.js')
  const writes = [], applied = [], timers = new Map()
  let sequence = 0, statuses = {}, incoming, connection, finishRead
  const schedule = (fn) => { timers.set(++sequence, fn); return sequence }
  const tracker = createLightCommandReceiptTracker({
    onUpdate: (value) => { statuses = value }, generateId: () => `home_command_${++sequence}`,
    schedule, cancel: (id) => timers.delete(id),
  })
  const store = { set() {}, update() {} }
  const context = vm.createContext({
    createLightCommands: (config) => createLightCommands({ ...config, uuid: () => 'offline_session_123',
      schedule, cancel: (id) => timers.delete(id) }),
    lightCommandTracker: tracker, applyLightUpdate: (light) => applied.push(light),
    apiGet: (path) => path === '/api/lights/2' ? new Promise(resolve => { finishRead = resolve }) : Promise.resolve({}),
    HubSocket: class {
      constructor(message, state) { incoming = message; connection = state }
      connect() { connection(true) }
      send(type, data) { writes.push({ type, ...data }); return true }
      close() { connection(false) }
    },
    resetAmbientContext() {}, startWeatherPolling() {}, stopWeatherPolling() {},
    setLightsFromList() {}, automationStateFromStatus: x => x, addError() {},
    sonos: store, automation: store, ambient: store, camera: store, pipeline: store,
    connected: store, deviceStatus: store,
  })
  const script = readFileSync(new URL('../../src/lib/stores/init.js', import.meta.url), 'utf8')
    .replace(/^import .*$/gm, '').replace(/export /g, '')
  vm.runInContext(script + '\nconst cleanup = initStores()', context)
  await tick()
  vm.runInContext("setLight('2', {on:false}, {optimistic:false})", context)
  assert.equal(writes.length, 0, 'capability required')
  incoming({ type: 'connection_status', data: { light_command_results: true } })
  vm.runInContext("setLight('2', {on:false}, {optimistic:false})", context)
  assert.equal(writes.length, 1)
  assert.equal(statuses['2'].commandId, writes[0].command_id)
  assert.equal(statuses['2'].status, 'pending')
  assert.deepEqual(applied, [])
  incoming({ type: 'light_command_result', data: { ...writes[0], status: 'denied' } })
  assert.equal(statuses['2'].status, 'denied')
  incoming({ type: 'light_update', data: { ...observation, bri: 140 } })
  finishRead(observation)
  await tick()
  assert.deepEqual(applied, [{ ...observation, bri: 140 }])
  vm.runInContext("setLight('2', {bri:120}, {optimistic:false})", context)
  incoming({ type: 'light_command_result', data: { ...writes[1], status: 'acknowledged' } })
  assert.equal(statuses['2'].status, 'acknowledged')
  assert.equal(applied.length, 1, 'ACK cannot fabricate physical state')
  vm.runInContext("setLight('2', {bri:100}, {optimistic:false})", context)
  connection(false)
  assert.equal(statuses['2'].status, 'uncertain')
  vm.runInContext('cleanup()', context)
  assert.equal(timers.size, 0)
  assert.equal(writes.length, 3, 'disconnect and cleanup cannot retry commands')
})
