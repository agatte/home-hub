import { describe, it, expect, vi } from 'vitest'
import { HOLD_KEY, recoverHold, saveHold, interpretHold, requestHold } from '../../src/lib/hueAppHold.js'

describe('L6 Hue app ownership recovery', () => {
  const previous = { stamp: 'original', kind: 'unverified' }
  it('recovers only an unverified token, never an active claim', () => {
    const storage = { getItem: () => JSON.stringify({ stamp: 'original', kind: 'acknowledged' }) }
    expect(recoverHold(storage)).toEqual(previous)
    expect(recoverHold({ getItem: () => '{' })).toBeNull()
    expect(recoverHold({ getItem: () => JSON.stringify({ stamp: 42 }) })).toBeNull()
    expect(recoverHold(undefined)).toBeNull()
  })
  it('reports storage failures and saves only the recovery token', () => {
    const storage = { setItem: vi.fn(), removeItem: vi.fn() }
    expect(saveHold(storage, previous)).toBe(true)
    expect(storage.setItem).toHaveBeenCalledWith(HOLD_KEY, '{"stamp":"original"}')
    expect(saveHold(undefined, previous)).toBe(false)
    saveHold(storage, { kind: 'released' })
    expect(storage.removeItem).toHaveBeenCalledWith(HOLD_KEY)
  })
  it('accepts only well-formed acknowledgements', () => {
    expect(interpretHold(200, { status: 'held', stamp: 'new' }, false).kind).toBe('acknowledged')
    expect(interpretHold(200, { status: 'held' }, false).kind).toBe('uncertain')
    expect(interpretHold(200, { status: 'released' }, true, previous)).toEqual({ kind: 'released', stamp: null })
  })
  it.each([true, false])('does not adopt a newer owner stamp on failed release (active=%s)', active => {
    expect(interpretHold(503, { detail: { stamp: 'competing-owner', active_in_memory: active } }, true, previous))
      .toEqual({ kind: 'uncertain', stamp: 'original', activeInMemory: active })
  })
  it.each([true, false])('keeps only a server-provided claim recovery stamp (active=%s)', active => {
    expect(interpretHold(503, { detail: { stamp: 'possible', active_in_memory: active } }, false, null))
      .toEqual({ kind: 'uncertain', stamp: 'possible', activeInMemory: active })
  })
  it('never uses a competing recovery token in a subsequent release request', async () => {
    const server = vi.fn().mockResolvedValue({ status: 503, json: async () => ({
      detail: { stamp: 'newer-dashboard-owner', active_in_memory: true },
    }) })
    const failedRelease = await requestHold(true, previous, server)
    expect(failedRelease.stamp).toBe('original')
    await requestHold(true, failedRelease, server)
    expect(JSON.parse(server.mock.calls[1][1].body)).toEqual({ stamp: 'original' })
    expect(server).toHaveBeenCalledTimes(2)
  })
  it('fails closed on conflict and retains the original token', () => {
    expect(interpretHold(409, { stamp: 'competitor' }, true, previous))
      .toEqual({ kind: 'conflict', stamp: 'original' })
  })
  it('sends only L6 metadata and exact release stamp, without retries', async () => {
    const fetcher = vi.fn().mockResolvedValue({ status: 503, json: async () => ({ detail: { stamp: 'possible' } }) })
    const result = await requestHold(false, null, fetcher)
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(fetcher.mock.calls[0][0]).toBe('/api/lights/6/hue-app-hold')
    expect(fetcher.mock.calls[0][1].body).toBeUndefined()
    await requestHold(true, result, fetcher)
    expect(fetcher.mock.calls[1][1].method).toBe('DELETE')
    expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({ stamp: 'possible' })
  })
  it('retains recovery on network and malformed-response failures', async () => {
    const fetcher = vi.fn().mockRejectedValue(new Error('offline'))
    expect(await requestHold(true, previous, fetcher)).toEqual({ kind: 'uncertain', stamp: 'original' })
    expect(fetcher).toHaveBeenCalledTimes(1)
    const malformed = vi.fn().mockResolvedValue({ status: 200, json: async () => { throw new Error('bad JSON') } })
    expect((await requestHold(true, previous, malformed)).stamp).toBe('original')
    await expect(requestHold(true, null, fetcher)).rejects.toThrow('Missing matching stamp')
    expect(fetcher).toHaveBeenCalledTimes(1)
  })
})
