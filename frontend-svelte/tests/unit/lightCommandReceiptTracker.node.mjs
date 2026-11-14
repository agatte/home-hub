import test from 'node:test'
import assert from 'node:assert/strict'
import { createLightCommandReceiptTracker } from '../../src/lib/quietAtlas/lightCommandReceiptTracker.js'

function fixture() {
  const updates = []
  const timers = new Map()
  let nextTimer = 0
  let counter = 0
  const tracker = createLightCommandReceiptTracker({
    onUpdate: (s) => updates.push(s),
    generateId: () => `cmd_test_${++counter}`,
    schedule: (fn) => { timers.set(++nextTimer, fn); return nextTimer },
    cancel: (id) => timers.delete(id),
    timeoutMs: 12000,
  })
  return { tracker, updates, timers }
}

test('incompatible backend never receives a fake-success request', () => {
  const { tracker } = fixture()
  let calls = 0
  assert.equal(tracker.submit('2', { on: true }, () => { calls += 1; return true }), 'unavailable')
  assert.equal(calls, 0)
  assert.equal(tracker.snapshot()['2'].status, 'unavailable')
})

test('correlated result matches only the original fixture and command', () => {
  const { tracker, timers } = fixture()
  tracker.setCapability(true)
  const outgoing = []
  assert.equal(tracker.submit('2', { bri: 110 }, (data) => { outgoing.push(data); return true }), 'pending')
  assert.equal(tracker.submit('2', { bri: 115 }, () => { throw Error('duplicate sent') }), 'pending')
  assert.equal(outgoing.length, 1)
  assert.equal(outgoing[0].command_id, 'cmd_test_1')
  assert.equal(tracker.receive({ command_id: 'cmd_test_1', light_id: '5', status: 'acknowledged' }), false)
  assert.equal(tracker.receive({ command_id: 'cmd_test_0', light_id: '2', status: 'acknowledged' }), false)
  assert.equal(tracker.receive({ command_id: 'cmd_test_1', light_id: '2', status: 'acknowledged' }), true)
  assert.equal(tracker.snapshot()['2'].status, 'acknowledged')
  assert.equal(timers.size, 0)
  assert.equal(tracker.receive({ command_id: 'cmd_test_1', status: 'denied' }), false)
  assert.equal(tracker.snapshot()['2'].status, 'acknowledged')
})

test('denied, invalid and uncertain results are distinct from transport acceptance', () => {
  const { tracker } = fixture()
  tracker.setCapability(true)
  tracker.submit('2', { on: false }, () => true)
  assert.equal(tracker.receive({ command_id: 'cmd_test_1', status: 'denied' }), true)
  assert.equal(tracker.snapshot()['2'].status, 'denied')
  tracker.submit('2', { bri: 101 }, () => true)
  assert.equal(tracker.receive({ command_id: 'cmd_test_2', status: 'invalid' }), true)
  assert.equal(tracker.snapshot()['2'].status, 'invalid')
  tracker.submit('2', { bri: 100 }, () => true)
  assert.equal(tracker.receive({ command_id: 'cmd_test_3', status: 'uncertain' }), true)
  assert.equal(tracker.snapshot()['2'].status, 'uncertain')
})

test('timeout and disconnect do not automatically replay any Hue action', () => {
  const { tracker, timers } = fixture()
  tracker.setCapability(true)
  let calls = 0
  tracker.submit('2', { bri: 90 }, () => { calls++; return true })
  const [onTimeout] = timers.values()
  onTimeout()
  assert.equal(tracker.snapshot()['2'].status, 'uncertain')
  assert.equal(calls, 1)
  tracker.submit('2', { bri: 92 }, () => { calls++; return true })
  tracker.disconnect()
  assert.equal(tracker.snapshot()['2'].status, 'uncertain')
  assert.equal(calls, 2)
  assert.equal(tracker.submit('2', { bri: 93 }, () => { calls++; return true }), 'unavailable')
  assert.equal(calls, 2)
})

test('failed send and reset do not leak pending timers', () => {
  const { tracker, timers } = fixture()
  tracker.setCapability(true)
  assert.equal(tracker.submit('3', { on: true }, () => false), 'unavailable')
  assert.equal(timers.size, 0)
  tracker.submit('4', { bri: 120 }, () => true)
  assert.equal(timers.size, 1)
  tracker.reset()
  assert.deepEqual(tracker.snapshot(), {})
  assert.equal(timers.size, 0)
  assert.equal(tracker.receive({ command_id: 'cmd_test_2', status: 'acknowledged' }), false)
})
