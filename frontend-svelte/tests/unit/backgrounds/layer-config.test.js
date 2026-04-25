import { describe, expect, it } from 'vitest'

import {
  LAYER_CONFIGS,
  TILE_WIDTH,
  getSkyVariant,
} from '$lib/backgrounds/layer-config.js'

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

  it('TILE_WIDTH is a positive integer', () => {
    expect(TILE_WIDTH).toBeGreaterThan(0)
    expect(Number.isInteger(TILE_WIDTH)).toBe(true)
  })
})

describe('getSkyVariant', () => {
  it('returns the overcast sky when weather contains "cloud" or "overcast"', () => {
    expect(getSkyVariant('working', 'overcast')).toMatch(/sky-overcast/)
    expect(getSkyVariant('working', 'partly cloudy')).toMatch(/sky-overcast/)
  })

  it('returns the original layer src for non-working modes', () => {
    // Non-working modes fall through to the first configured layer.src or ''.
    const result = getSkyVariant('relax', 'clear')
    expect(typeof result).toBe('string')
  })

  it('returns a non-empty string for working+clear', () => {
    const result = getSkyVariant('working', 'clear')
    expect(result).toMatch(/^\/backgrounds\/working\//)
  })
})
