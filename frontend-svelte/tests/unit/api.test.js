import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { get } from 'svelte/store'

import { apiGet, apiPost, apiPut, apiDelete } from '$lib/api.js'
import { errors } from '$lib/stores/errors.js'

function mockResponse({ ok = true, status = 200, body = '{}' } = {}) {
  return {
    ok,
    status,
    text: vi.fn().mockResolvedValue(body),
  }
}

function fetchOnce(value) {
  globalThis.fetch = vi.fn().mockResolvedValueOnce(value)
}

function fetchOnceRejecting(error) {
  globalThis.fetch = vi.fn().mockRejectedValueOnce(error)
}

describe('apiGet', () => {
  beforeEach(() => {
    errors.set([])
  })

  it('returns parsed JSON on 2xx', async () => {
    fetchOnce(mockResponse({ body: '{"ok":1}' }))
    const result = await apiGet('/api/foo')
    expect(result).toEqual({ ok: 1 })
    expect(get(errors)).toHaveLength(0)
  })

  it('surfaces non-OK status as an error toast and throws', async () => {
    fetchOnce(mockResponse({ ok: false, status: 500, body: '' }))
    await expect(apiGet('/api/bar')).rejects.toThrow(/500/)
    const list = get(errors)
    expect(list).toHaveLength(1)
    expect(list[0].message).toMatch(/GET \/api\/bar: 500/)
  })

  it('surfaces network error as a toast and throws', async () => {
    fetchOnceRejecting(new TypeError('failed to fetch'))
    await expect(apiGet('/api/x')).rejects.toThrow()
    const list = get(errors)
    expect(list).toHaveLength(1)
    expect(list[0].message).toMatch(/network error/)
  })
})

describe('JSON body parsing', () => {
  beforeEach(() => {
    errors.set([])
  })

  it('returns null when body is empty (HTTP 204 style)', async () => {
    fetchOnce(mockResponse({ body: '' }))
    const result = await apiPost('/api/empty')
    expect(result).toBeNull()
    expect(get(errors)).toHaveLength(0)
  })

  it('surfaces malformed JSON as an error and throws', async () => {
    fetchOnce(mockResponse({ body: '{not-json' }))
    await expect(apiPost('/api/garbled')).rejects.toThrow()
    expect(get(errors)[0].message).toMatch(/malformed JSON/)
  })

  it('parses valid JSON body on POST', async () => {
    fetchOnce(mockResponse({ body: '{"id":42}' }))
    const result = await apiPost('/api/create', { name: 'x' })
    expect(result).toEqual({ id: 42 })
  })
})

describe('apiPost / apiPut / apiDelete', () => {
  beforeEach(() => {
    errors.set([])
  })

  it('apiPost sets JSON content-type when a body is provided', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(mockResponse({ body: '{}' }))
    globalThis.fetch = fetch
    await apiPost('/api/x', { foo: 'bar' })
    const init = fetch.mock.calls[0][1]
    expect(init.method).toBe('POST')
    expect(init.headers['Content-Type']).toBe('application/json')
    expect(init.body).toBe(JSON.stringify({ foo: 'bar' }))
  })

  it('apiPost without body omits content-type and body', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(mockResponse({ body: '{}' }))
    globalThis.fetch = fetch
    await apiPost('/api/x')
    const init = fetch.mock.calls[0][1]
    expect(init.headers).toEqual({})
    expect(init.body).toBeUndefined()
  })

  it('apiPut always sends JSON body', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(mockResponse({ body: '{}' }))
    globalThis.fetch = fetch
    await apiPut('/api/x', { a: 1 })
    const init = fetch.mock.calls[0][1]
    expect(init.method).toBe('PUT')
    expect(init.body).toBe(JSON.stringify({ a: 1 }))
  })

  it('apiDelete sends DELETE with no body', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(mockResponse({ body: '' }))
    globalThis.fetch = fetch
    const result = await apiDelete('/api/x')
    expect(fetch.mock.calls[0][1].method).toBe('DELETE')
    expect(result).toBeNull()
  })
})

describe('safeFetch timeout', () => {
  beforeEach(() => {
    errors.set([])
  })

  it('aborts via AbortController on timeout and surfaces the timeout', async () => {
    // Real timers + a fetch that resolves only when its signal aborts.
    // Avoids fake-timer interaction with jsdom's AbortSignal dispatch.
    globalThis.fetch = vi.fn().mockImplementation((url, init) => new Promise((_, reject) => {
      if (init.signal.aborted) {
        reject(new DOMException('aborted', 'AbortError'))
        return
      }
      init.signal.addEventListener('abort', () => {
        reject(new DOMException('aborted', 'AbortError'))
      }, { once: true })
    }))

    await expect(apiGet('/api/slow', undefined, { timeout: 50 })).rejects.toThrow()
    const list = get(errors)
    expect(list).toHaveLength(1)
    expect(list[0].message).toMatch(/timed out/)
  })
})
