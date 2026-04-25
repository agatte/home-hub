import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { get } from 'svelte/store'

import { errors, addError } from '$lib/stores/errors.js'

beforeEach(() => {
  errors.set([])
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('addError', () => {
  it('appends an error with a unique id', () => {
    addError('boom')
    addError('again')
    const list = get(errors)
    expect(list).toHaveLength(2)
    expect(list[0].message).toBe('boom')
    expect(list[1].message).toBe('again')
    expect(list[0].id).not.toBe(list[1].id)
  })

  it('auto-removes the entry after 5 seconds', () => {
    addError('temp')
    expect(get(errors)).toHaveLength(1)
    vi.advanceTimersByTime(5000)
    expect(get(errors)).toHaveLength(0)
  })

  it('only removes the matching id when multiple errors are stacked', () => {
    addError('first')
    vi.advanceTimersByTime(2000)
    addError('second')
    expect(get(errors)).toHaveLength(2)
    vi.advanceTimersByTime(3000) // first hits 5s, second is at 3s
    const list = get(errors)
    expect(list).toHaveLength(1)
    expect(list[0].message).toBe('second')
  })
})
