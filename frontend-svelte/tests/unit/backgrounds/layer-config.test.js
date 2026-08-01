import { describe, expect, it } from 'vitest'

import { LAYER_CONFIGS } from '$lib/backgrounds/layer-config.js'

describe('LAYER_CONFIGS', () => {
  it('exposes a working entry with the expected shape', () => {
    expect(Array.isArray(LAYER_CONFIGS.working)).toBe(true)
    expect(LAYER_CONFIGS.working.length).toBeGreaterThan(0)
    const layer = LAYER_CONFIGS.working[0]
    expect(typeof layer.src).toBe('string')
    expect(typeof layer.duration).toBe('number')
    expect(typeof layer.opacity).toBe('number')
    expect(typeof layer.zIndex).toBe('number')
  })
})
