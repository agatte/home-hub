import { beforeEach, describe, expect, it } from 'vitest'
import { get } from 'svelte/store'

import {
  modeSuggestion,
  showModeSuggestion,
  dismissModeSuggestion,
} from '$lib/stores/modeSuggestion.js'

const sample = {
  suggestion_id: 7, rule_id: 1, predicted_mode: 'relax', confidence: 0.8,
  sample_count: 12, message: 'Try relax?',
}

beforeEach(() => {
  modeSuggestion.set(null)
})

describe('showModeSuggestion', () => {
  it('sets the store value', () => {
    showModeSuggestion(sample)
    expect(get(modeSuggestion)).toEqual(sample)
  })

  it('does not auto-dismiss — expiry is server-driven', () => {
    // The 20s client-side auto-hide was removed; the server expires the
    // suggestion via `mode_suggestion_dismissed` (60min automation-tick
    // auto-expire). The store value persists until explicitly cleared.
    showModeSuggestion(sample)
    expect(get(modeSuggestion)).toEqual(sample)
  })

  it('a second call replaces the value', () => {
    showModeSuggestion(sample)
    showModeSuggestion({ ...sample, predicted_mode: 'gaming' })
    expect(get(modeSuggestion)?.predicted_mode).toBe('gaming')
  })
})

describe('dismissModeSuggestion', () => {
  it('clears the value immediately', () => {
    showModeSuggestion(sample)
    dismissModeSuggestion()
    expect(get(modeSuggestion)).toBeNull()
  })

  it('a show after dismiss keeps the new value', () => {
    showModeSuggestion(sample)
    dismissModeSuggestion()
    showModeSuggestion(sample)
    expect(get(modeSuggestion)).toEqual(sample)
  })
})
