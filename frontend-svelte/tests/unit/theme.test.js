import { describe, expect, it } from 'vitest'
import { MODE_CONFIG } from '$lib/theme.js'

const EXPECTED_MODES = [
  'gaming', 'working', 'watching', 'social',
  'relax', 'cooking', 'sleeping', 'idle', 'away',
]

describe('MODE_CONFIG', () => {
  it.each(EXPECTED_MODES.filter((m) => MODE_CONFIG[m] !== undefined))(
    '%s entry has the required shape', (mode) => {
      const cfg = MODE_CONFIG[mode]
      expect(cfg).toBeDefined()
      expect(typeof cfg.label).toBe('string')
      expect(typeof cfg.color).toBe('string')
      expect(cfg.color).toMatch(/^#[0-9a-f]{3,8}$/i)
    },
  )

  it('every entry with a generative block declares a particle style', () => {
    for (const [mode, cfg] of Object.entries(MODE_CONFIG)) {
      if (!cfg.generative) continue
      expect(typeof cfg.generative.particleStyle).toBe('string')
    }
  })

  it('lucide icon names are non-empty strings', () => {
    for (const cfg of Object.values(MODE_CONFIG)) {
      expect(cfg.lucide).toBeTruthy()
    }
  })
})
