import { describe, expect, it } from 'vitest'
import { createLightCommandReceiptTracker } from '../../src/lib/quietAtlas/lightCommandReceiptTracker.js'
import card from '../../src/lib/components/LightCard.svelte?raw'
import init from '../../src/lib/stores/init.js?raw'
import ws from '../../src/lib/ws.js?raw'
import { compile } from 'svelte/compiler'

function harness() {
  const sent = []
  const timers = new Map()
  let seq = 0
  const tracker = createLightCommandReceiptTracker({
    onUpdate: () => {},
    generateId: () => `cmd_test_${++seq}`,
    schedule: (fn) => { timers.set(seq, fn); return seq },
    cancel: (id) => timers.delete(id),
  })
  return { tracker, timers, sent }
}

describe('correlated guarded light WebSocket receipts (#461)', () => {
  it('refuses to send when the backend does not advertise results', () => {
    const { tracker, sent } = harness()
    expect(tracker.submit('2', { bri: 100 }, (d) => { sent.push(d); return true })).toBe('unavailable')
    expect(sent).toHaveLength(0)
    expect(tracker.snapshot()['2'].status).toBe('unavailable')
  })

  it('uses one pending command per fixture and cannot accept a late or cross-fixture result', () => {
    const { tracker, sent } = harness()
    tracker.setCapability(true)
    expect(tracker.submit('2', { on: true }, (d) => { sent.push(d); return true })).toBe('pending')
    expect(tracker.submit('2', { bri: 200 }, (d) => { sent.push(d); return true })).toBe('pending')
    expect(sent).toHaveLength(1)
    expect(tracker.receive({ command_id: sent[0].command_id, light_id: '3', status: 'acknowledged' })).toBe(false)
    expect(tracker.receive({ command_id: sent[0].command_id, light_id: '2', status: 'denied' })).toBe(true)
    expect(tracker.snapshot()['2'].status).toBe('denied')
    expect(tracker.receive({ command_id: sent[0].command_id, status: 'acknowledged' })).toBe(false)
    expect(tracker.snapshot()['2'].status).toBe('denied')
  })

  it('disconnect and timeout explicitly yield uncertainty without auto retries', () => {
    const { tracker, sent, timers } = harness()
    tracker.setCapability(true)
    tracker.submit('5', { on: false }, (d) => { sent.push(d); return true })
    expect(timers.size).toBe(1)
    tracker.disconnect()
    expect(tracker.snapshot()['5'].status).toBe('uncertain')
    expect(timers.size).toBe(0)
    expect(sent).toHaveLength(1)
    tracker.setCapability(true)
    tracker.submit('5', { bri: 91 }, (d) => { sent.push(d); return true })
    ;[...timers.values()][0]()
    expect(tracker.snapshot()['5'].status).toBe('uncertain')
    expect(sent).toHaveLength(2)
  })

  it('keeps redesigned light values source-qualified with explicit status text', () => {
    expect(card).toContain('export let optimisticStore = true')
    expect(card).toContain('if (!optimisticStore) return')
    expect(card).toContain("lightCommandResults")
    expect(card).toContain("commandPending")
    expect(card).toContain('role="status" aria-live="polite"')
    expect(card).toContain('Actual light state awaits a fresh report.')
    expect(init).toContain("lightCommandTracker.setCapability(data?.light_command_results === true)")
    expect(init).toContain("case 'light_command_result':")
    expect(init).toContain("lightCommandTracker.submit(lightId, state")
    expect(ws).toContain('return false')
    expect(compile(card, { filename: 'LightCard.svelte', generate: 'dom', css: 'external' }).warnings).toEqual([])
  })
})
