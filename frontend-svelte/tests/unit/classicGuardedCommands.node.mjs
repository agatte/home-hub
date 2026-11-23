import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import { createLightCommandReceiptTracker } from '../../src/lib/quietAtlas/lightCommandReceiptTracker.js'

const init = readFileSync(new URL('../../src/lib/stores/init.js', import.meta.url), 'utf8')
const card = readFileSync(new URL('../../src/lib/components/LightCard.svelte', import.meta.url), 'utf8')
const fn = (text, start, end) => text.slice(text.indexOf(start), text.indexOf(end, text.indexOf(start)))

test('actual setLight sends correlated commands without patching reported state', () => {
  const lights = { '3': { bri: 50 }, '4': { bri: 60 } }
  const sent = []
  let number = 0
  const tracker = createLightCommandReceiptTracker({ onUpdate() {}, generateId: () => `command_${++number}` })
  const setLight = runInNewContext(`(${fn(init, 'export function setLight(', '\n/**').replace('export ', '')})`, {
    lightCommandTracker: tracker, socket: { send: (_, data) => { sent.push(data); return true } },
    optimisticLightPatch: () => { throw Error('optimistic patch') },
  })
  setLight('3', { bri: 100 })
  assert.equal(sent.length, 0)
  tracker.setCapability(true)
  setLight('3', { bri: 100 })
  setLight('3', { bri: 200 })
  setLight('4', { bri: 100 })
  assert.deepEqual(sent.map(x => x.light_id), ['3', '4'])
  tracker.receive({ command_id: sent[0].command_id, light_id: '3', status: 'denied' })
  tracker.receive({ command_id: sent[1].command_id, light_id: '4', status: 'acknowledged' })
  assert.equal(lights['3'].bri, 50)
  assert.equal(lights['4'].bri, 60)
  setLight('3', { bri: 150 })
  assert.equal(tracker.receive({ command_id: sent[0].command_id, light_id: '3', status: 'denied' }), false)
  assert.equal(tracker.snapshot()['3'].status, 'pending')
  tracker.disconnect()
  assert.equal(tracker.snapshot()['3'].status, 'uncertain')
  setLight('3', { bri: 210 })
  assert.equal(sent.length, 3)
})

test('actual drag handlers preview motion and cancel without sending', () => {
  const handlers = fn(card, '  function onPointerDown(e)', '  /** @param {KeyboardEvent} e */')
  const result = runInNewContext(`
    let light = { light_id: '3', reachable: true, on: true, bri: 50 };
    let commandPending = false, controlUnavailable = false, dragging = false, activePointerId = null;
    let dragStartX = 0, didDrag = false, dragPowerRequested = false, pendingBri = null, optimisticBri = null;
    let throttleTimer = null, pendingState = null, writes = 0;
    const DRAG_THRESHOLD_PX = 4;
    const cardEl = { setPointerCapture(){}, releasePointerCapture(){}, getBoundingClientRect(){ return {left:0,width:100} } };
    function clampedBriFromX(x) { return Math.round(x * 2) }
    function flushBrightness() { writes++ }
    ${handlers}
    onPointerDown({pointerId:1, pointerType:'mouse', clientX:10});
    onPointerMove({pointerId:1, clientX:80});
    onPointerCancel({pointerId:1});
    ({writes, dragging, optimisticBri})
  `)
  assert.equal(result.writes, 0)
  assert.equal(result.dragging, false)
  assert.equal(result.optimisticBri, null)
})

test('actual grouped fanout addresses each fixture and blocks while either is pending', () => {
  const body = fn(card, '  function fanout(id, state)', '\n  const COLOR_PRESETS')
  const calls = []
  const context = { linkedIds: ['4'], commandPending: false, controlUnavailable: false, setLight: (id, state) => calls.push(id) }
  const invoke = runInNewContext(`(${body.trim()})`, context)
  invoke('3', { on: true })
  assert.deepEqual(calls, ['3', '4'])
  context.commandPending = true
  invoke('3', { on: false })
  assert.deepEqual(calls, ['3', '4'])
})

test('replacement socket rejects old status and requires a new capability handshake', async () => {
  const { HubSocket } = await import('../../src/lib/ws.js')
  const instances = []
  class FakeSocket {
    static OPEN = 1
    static CONNECTING = 0
    constructor() { this.readyState = 1; instances.push(this) }
    close() { this.readyState = 3 }
    send() {}
  }
  globalThis.WebSocket = FakeSocket
  globalThis.window = { location: { protocol: 'http:', host: 'fake' } }
  let capable = false
  const tracker = createLightCommandReceiptTracker({ onUpdate() {}, generateId: () => 'command_1' })
  const socket = new HubSocket(msg => { if (msg.type === 'connection_status') { capable = msg.data.light_command_results === true; tracker.setCapability(capable) } }, connected => { if (!connected) { capable = false; tracker.disconnect() } })
  socket.connect()
  const first = instances[0]
  first.onmessage({ data: JSON.stringify({type:'connection_status',data:{light_command_results:true}}) })
  tracker.submit('3', {}, () => true)
  socket.connect()
  assert.equal(capable, false)
  assert.equal(tracker.snapshot()['3'].status, 'uncertain')
  first.onmessage({ data: JSON.stringify({type:'connection_status',data:{light_command_results:true}}) })
  first.onclose()
  assert.equal(capable, false)
  assert.equal(tracker.submit('3', {}, () => { throw Error('sent before handshake') }), 'unavailable')
  instances[1].onmessage({ data: JSON.stringify({type:'connection_status',data:{light_command_results:true}}) })
  assert.equal(capable, true)
  socket.close()
  delete globalThis.WebSocket
  delete globalThis.window
})
