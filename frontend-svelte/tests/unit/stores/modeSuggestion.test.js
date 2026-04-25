import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { get } from 'svelte/store'

import {
  modeSuggestion,
  showModeSuggestion,
  dismissModeSuggestion,
} from '$lib/stores/modeSuggestion.js'

const sample = {
  rule_id: 1, predicted_mode: 'relax', confidence: 0.8,
  sample_count: 12, message: 'Try relax?',
}

beforeEach(() => {
  modeSuggestion.set(null)
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('showModeSuggestion', () => {
  it('sets the store value', () => {
    showModeSuggestion(sample)
    expect(get(modeSuggestion)).toEqual(sample)
  })

  it('auto-dismisses after 20 seconds', () => {
    showModeSuggestion(sample)
    vi.advanceTimersByTime(20_000)
    expect(get(modeSuggestion)).toBeNull()
  })

  it('a second call resets the auto-dismiss timer', () => {
    showModeSuggestion(sample)
    vi.advanceTimersByTime(15_000)
    showModeSuggestion({ ...sample, predicted_mode: 'gaming' })
    vi.advanceTimersByTime(15_000)
    // 30s total elapsed but timer was reset at 15s — still alive at 30s.
    expect(get(modeSuggestion)?.predicted_mode).toBe('gaming')
    vi.advanceTimersByTime(10_000)
    expect(get(modeSuggestion)).toBeNull()
  })
})

describe('dismissModeSuggestion', () => {
  it('clears the value immediately', () => {
    showModeSuggestion(sample)
    dismissModeSuggestion()
    expect(get(modeSuggestion)).toBeNull()
  })

  it('cancels the pending auto-dismiss so a later show isn\'t cut short', () => {
    showModeSuggestion(sample)
    vi.advanceTimersByTime(10_000)
    dismissModeSuggestion()
    showModeSuggestion(sample)
    vi.advanceTimersByTime(10_000)
    // 20s would have elapsed since first show, but dismiss reset the timer
    // to a fresh window.
    expect(get(modeSuggestion)).not.toBeNull()
  })
})
