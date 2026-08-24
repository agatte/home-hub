import { describe, expect, it } from 'vitest'
import {
  DEFAULT_SYNTHETIC_PREVIEW_STATE,
  resolveSyntheticPreviewState,
  SYNTHETIC_PREVIEW_STATES,
} from './live-state.js'

describe('Apartment Canvas synthetic preview state', () => {
  it('defaults to rest', () => {
    expect(resolveSyntheticPreviewState('').id).toBe(DEFAULT_SYNTHETIC_PREVIEW_STATE)
  })

  it('selects the desk fixture deterministically', () => {
    const state = resolveSyntheticPreviewState('?state=desk')
    expect(state).toBe(SYNTHETIC_PREVIEW_STATES.desk)
    expect(state.activeZone).toBe('bedroom.desk')
    expect(state.lamps.bedroomL2).toBe(true)
    expect(state.lamps.bedroomL5).toBe(true)
    expect(state.displays.monitor).toBe(true)
  })

  it('falls back to rest for unknown state names', () => {
    expect(resolveSyntheticPreviewState('?state=not-a-state')).toBe(SYNTHETIC_PREVIEW_STATES.rest)
  })
})
