import { describe, expect, it } from 'vitest'
import { weatherTone, activityTone } from '../../src/lib/quietAtlas/widgetTone.js'
import home from '../../src/routes/quiet-atlas/home/+page.svelte?raw'
import weather from '../../src/lib/components/QuietAtlasEnvironment.svelte?raw'
import modes from '../../src/lib/components/QuietAtlasHomeModeControls.svelte?raw'

describe('HomeHub widget palette', () => {
  it('selects accents from reported weather, never inventing a condition', () => {
    for (const [description, tone] of [
      ['Sunny', 'sun'], ['Mostly Clear', 'clear'], ['Mostly cloudy', 'cloud'],
      ['Light Rain', 'rain'], ['Thunderstorms', 'storm'], ['Freezing Rain', 'snow'],
      ['Unrecognized description', 'neutral'],
    ]) expect(weatherTone({ status: 'recent', report: { description } })).toBe(tone)
    for (const status of ['loading', 'stale', 'disconnected', 'unavailable'])
      expect(weatherTone({ status, report: { description: 'Sunny' } })).toBe('neutral')
    expect(weatherTone(null)).toBe('neutral')
  })
  it('uses known activity labels and neutral unknown values', () => {
    for (const [label, tone] of [
      ['Working', 'focus'], ['Gaming', 'play'], ['Watching', 'cinema'],
      ['Cooking', 'warm'], ['Relaxing', 'calm'], ['Social', 'social'],
      ['General', 'neutral'], ['Unverified', 'neutral'],
    ]) expect(activityTone(label)).toBe(tone)
  })
  it('keeps Home widget appearance within shared tokens', () => {
    for (const source of [home, weather, modes]) {
      expect(source).toContain('var(--hh-card-background')
      expect(source).toContain('var(--hh-radius-panel')
    }
    expect(home).toContain('data-tone={activityTone(entry.label)}')
    expect(weather).toContain('data-tone={weatherTone(view)}')
  })
})
