import { describe, expect, it } from 'vitest'

import {
  hexToRGB,
  createStars,
  createRainDrops,
  createSnowFlakes,
} from '$lib/backgrounds/scene-utils.js'

describe('hexToRGB', () => {
  it('parses a 6-digit hex string', () => {
    expect(hexToRGB('#ff8040')).toEqual({ r: 255, g: 128, b: 64 })
  })

  it('parses pure white and black', () => {
    expect(hexToRGB('#ffffff')).toEqual({ r: 255, g: 255, b: 255 })
    expect(hexToRGB('#000000')).toEqual({ r: 0, g: 0, b: 0 })
  })
})

describe('createStars', () => {
  it('returns the requested count', () => {
    const stars = createStars(50, 1920, 1080)
    expect(stars).toHaveLength(50)
  })

  it('places stars within the requested bounds', () => {
    const stars = createStars(20, 200, 100)
    for (const s of stars) {
      expect(s.x).toBeGreaterThanOrEqual(0)
      expect(s.x).toBeLessThan(200)
      expect(s.y).toBeGreaterThanOrEqual(0)
      expect(s.y).toBeLessThan(100)
    }
  })

  it('every star carries phase and size fields', () => {
    const [s] = createStars(1, 100, 100)
    expect(typeof s.phase).toBe('number')
    expect(typeof s.size).toBe('number')
  })
})

describe('createRainDrops', () => {
  it('returns the requested count with sane defaults', () => {
    const drops = createRainDrops(30, 1920, 1080)
    expect(drops).toHaveLength(30)
    for (const d of drops) {
      expect(d.speed).toBeGreaterThan(0)
      expect(d.length).toBeGreaterThan(0)
      expect(d.opacity).toBeGreaterThan(0)
    }
  })
})

describe('createSnowFlakes', () => {
  it('returns the requested count with size + drift', () => {
    const flakes = createSnowFlakes(15, 1920, 1080)
    expect(flakes).toHaveLength(15)
    for (const f of flakes) {
      expect(f.size).toBeGreaterThan(0)
      expect(typeof f.drift).toBe('number')
    }
  })
})
