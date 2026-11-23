import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'

const source = readFileSync(new URL('../../src/lib/components/LightCard.svelte', import.meta.url), 'utf8')
const start = source.indexOf('  function onPointerCancel(e) {')
const end = source.indexOf('  /** @param {KeyboardEvent} e */', start)
assert.ok(start >= 0 && end > start, 'the cancelled-gesture handler exists')
const fn = source.slice(start, end).trim()

function simulateCancel({ queued = false } = {}) {
  return runInNewContext(`
    let dragging = true
    let activePointerId = 7
    let didDrag = true
    let dragPowerRequested = true
    let pendingBri = 210
    let optimisticBri = 210
    let pendingState = ${queued ? '{ bri: 210 }' : 'null'}
    let throttleTimer = ${queued ? '42' : 'null'}
    const cardEl = { releasePointerCapture: () => {} }
    let canceledTimers = 0, writes = 0
    function clearTimeout() { canceledTimers++ }
    function fanout() { writes++ }
    ${fn}
    onPointerCancel({ pointerId: 7 });
    ({ dragging, activePointerId, didDrag, dragPowerRequested,
       pendingBri, optimisticBri, pendingState, throttleTimer, canceledTimers, writes })
  `)
}

test('cancelled dragged inline slider discards preview without a light write', () => {
  assert.match(source, /on:pointercancel=\{onPointerCancel\}/)
  assert.match(source, /on:pointerup=\{onPointerEnd\}/)
  const x = simulateCancel()
  assert.equal(x.writes, 0)
  assert.equal(x.dragging, false)
  assert.equal(x.activePointerId, null)
  assert.equal(x.pendingBri, null)
  assert.equal(x.optimisticBri, null)
})

test('cancel clears Classic queued throttle instead of flushing a new write', () => {
  const x = simulateCancel({ queued: true })
  assert.equal(x.writes, 0)
  assert.equal(x.canceledTimers, 1)
  assert.equal(x.throttleTimer, null)
  assert.equal(x.pendingState, null)
})
