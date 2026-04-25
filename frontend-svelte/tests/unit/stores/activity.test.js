import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { get } from 'svelte/store'

import { userIdle, initActivityTracking } from '$lib/stores/activity.js'

beforeEach(() => {
  vi.useFakeTimers()
  userIdle.set(false)
})

afterEach(() => {
  vi.useRealTimers()
})

describe('initActivityTracking', () => {
  it('starts as not-idle', () => {
    const cleanup = initActivityTracking()
    expect(get(userIdle)).toBe(false)
    cleanup()
  })

  it('flips to idle after the timeout', () => {
    const cleanup = initActivityTracking()
    vi.advanceTimersByTime(60_000)
    expect(get(userIdle)).toBe(true)
    cleanup()
  })

  it('a mouse event resets the idle timer', () => {
    const cleanup = initActivityTracking()
    vi.advanceTimersByTime(50_000)
    window.dispatchEvent(new Event('mousemove'))
    vi.advanceTimersByTime(50_000)
    // 100s elapsed but the reset at 50s gives us ~10s of headroom.
    expect(get(userIdle)).toBe(false)
    vi.advanceTimersByTime(20_000)
    expect(get(userIdle)).toBe(true)
    cleanup()
  })

  it('cleanup removes the event listeners', () => {
    const cleanup = initActivityTracking()
    cleanup()
    // After cleanup, mousemove should not affect the timer.
    vi.advanceTimersByTime(60_000)
    // userIdle is whatever the last reset/timeout set it to before cleanup.
    // Sending a mousemove now should NOT bring it out of idle.
    const before = get(userIdle)
    window.dispatchEvent(new Event('mousemove'))
    expect(get(userIdle)).toBe(before)
  })
})
