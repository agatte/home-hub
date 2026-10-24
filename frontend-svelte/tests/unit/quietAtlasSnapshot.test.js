import { describe, it, expect } from 'vitest'
import {
  newReadOnlySnapshot, connectionChanged, invalidateLightRead, beginLightRead,
  acceptLightRead, failLightRead, readStatus, permitsDeviceWrite,
} from '../../src/lib/quietAtlas/lightSnapshot.js'

const fixtures = [
  { light_id: '2', name: 'Shaded', on: true, bri: 111, reachable: true },
  { light_id: '5', name: 'Clear', on: false, bri: 28, reachable: true },
]
const connected = () => connectionChanged(newReadOnlySnapshot(), true)
function fresh(at = 1000) {
  const req = beginLightRead(connected())
  return acceptLightRead(req.state, req.ticket, fixtures, at)
}
describe('Quiet Atlas read-only light snapshot / reconnect (#270)', () => {
  it('starts unverified, never gives device write rights', () => {
    expect(readStatus(newReadOnlySnapshot(), 0)).toBe('disconnected')
    expect(readStatus(connected(), 1000)).toBe('unverified')
    expect(permitsDeviceWrite()).toBe(false)
  })
  it('separates a recent REST response from physical bulb age', () => {
    const state = fresh()
    expect(readStatus(state, 1000)).toBe('recent-read')
    expect(state.fixtures['2'].bri).toBe(111)
    expect(state.fixtures['5'].on).toBe(false)
    expect(readStatus(state, 31001)).toBe('stale-read')
    expect(readStatus(state, 999)).toBe('stale-read')
  })
  it('disconnect and reconnect always revoke prior read evidence', () => {
    const old = fresh()
    const disconnected = connectionChanged(old, false)
    const newer = connectionChanged(disconnected, true)
    expect(readStatus(disconnected, 1100)).toBe('disconnected')
    expect(readStatus(newer, 1100)).toBe('unverified')
    expect(newer.fixtures['2'].on).toBe(true)
    expect(newer.generation).toBe(old.generation + 2)
  })
  it('old GET after reconnect cannot restore false freshness', () => {
    const a = beginLightRead(connected())
    const next = connectionChanged(connectionChanged(a.state, false), true)
    expect(acceptLightRead(next, a.ticket, fixtures, 1100)).toBe(next)
    expect(readStatus(next, 1100)).toBe('unverified')
  })
  it('out-of-order reads and old failures never clobber latest result', () => {
    const first = beginLightRead(connected())
    const second = beginLightRead(first.state)
    expect(acceptLightRead(second.state, first.ticket, [], 2000)).toBe(second.state)
    const good = acceptLightRead(second.state, second.ticket, fixtures, 3000)
    expect(readStatus(good, 3000)).toBe('recent-read')
    expect(failLightRead(good, first.ticket)).toBe(good)
    expect(acceptLightRead(good, second.ticket, [], 4000)).toBe(good)
  })
  it('failed read keeps historical values but drops provenance', () => {
    const request = beginLightRead(fresh())
    const out = failLightRead(request.state, request.ticket)
    expect(readStatus(out, 4000)).toBe('unverified')
    expect(out.fixtures['2'].on).toBe(true)
  })
  it('malformed, duplicate and unsafe IDs reject the whole result', () => {
    for (const bad of [
      null, {}, [{ name: 'missing id' }],
      [fixtures[0], fixtures[0]], [{ light_id: '__proto__' }],
      [{ light_id: ' 2 ' }], [{ light_id: 2 }],
    ]) {
      const p = beginLightRead(fresh())
      const state = acceptLightRead(p.state, p.ticket, bad, 2000)
      expect(readStatus(state, 2000)).toBe('unverified')
      expect(state.fixtures['2'].on).toBe(true)
    }
  })
  it('empty list is not an off-state invention', () => {
    const p = beginLightRead(connected())
    const s = acceptLightRead(p.state, p.ticket, [], 2000)
    expect(readStatus(s, 2000)).toBe('recent-read')
    expect(Object.keys(s.fixtures)).toEqual([])
  })
  it('tab suspension invalidates pending ticket and previous freshness', () => {
    const pending = beginLightRead(fresh())
    const invalidated = invalidateLightRead(pending.state)
    expect(readStatus(invalidated, 1500)).toBe('unverified')
    expect(acceptLightRead(invalidated, pending.ticket, fixtures, 1700)).toBe(invalidated)
    expect(invalidated.fixtures['2'].on).toBe(true)
  })
  it('clock anomalies cannot produce a fresh snapshot', () => {
    const state = fresh()
    for (const v of [NaN, -1, Infinity]) {
      const p = beginLightRead(state)
      expect(readStatus(acceptLightRead(p.state, p.ticket, fixtures, v), 1000)).toBe('unverified')
    }
    expect(readStatus(state, NaN)).toBe('stale-read')
    expect(readStatus(state, 1200, 0)).toBe('stale-read')
  })
  it('beginning a read while disconnected is a strict no-op', () => {
    const s = newReadOnlySnapshot()
    const p = beginLightRead(s)
    expect(p.ticket).toBeNull()
    expect(p.state).toBe(s)
  })
})
