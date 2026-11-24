import { describe, expect, it } from 'vitest'
import { weatherTone, activityTone, weatherSky, weatherIconCode } from '../../src/lib/quietAtlas/widgetTone.js'
import { validateWeatherReport } from '../../src/lib/quietAtlas/weatherSnapshot.js'
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
  it('uses valid day/night icons to distinguish real reported sky conditions', () => {
    for (const [icon, sky] of [
      ['01d','sun'], ['01n','night'], ['02d','partly-day'], ['02n','partly-night'],
      ['03n','cloud-night'], ['04d','cloud'], ['10n','rain-night'], ['09d','rain'],
      ['11n','storm'], ['13d','snow'], ['50n','mist'],
    ]) expect(weatherSky({status:'recent',report:{description:'Clear',icon}})).toBe(sky)
    expect(weatherSky({status:'stale',report:{description:'Clear',icon:'01n'}})).toBe('neutral')
    expect(weatherSky({status:'recent',report:{description:'Clear',icon:'unknown'}})).toBe('clear')
    expect(weatherIconCode('url(unsafe)')).toBeNull()
    const weather = {temp:28,description:'Clear',city:'Home',icon:'01n'}
    expect(validateWeatherReport({status:'ok',weather})?.icon).toBe('01n')
    expect(validateWeatherReport({status:'ok',weather:{...weather,icon:'bad'}})).not.toHaveProperty('icon')
  })
  it('uses known activity labels and neutral unknown values', () => {
    for (const [label, tone] of [
      ['Working', 'focus'], ['Gaming', 'play'], ['Watching', 'cinema'],
      ['Cooking', 'warm'], ['Relaxing', 'calm'], ['Social', 'social'],
      ['General', 'neutral'], ['Unverified', 'neutral'],
    ]) expect(activityTone(label)).toBe(tone)
  })
  it('keeps Home widget appearance within shared tokens', () => {
    expect(home).toContain('var(--hh-card-background')
    expect(home).toContain('var(--hh-radius-panel')
    // Mode controls intentionally no longer use a nested panel or card tiles.
    expect(modes).not.toContain('var(--hh-card-background')
    expect(modes).toContain('data-palette={modeTone(mode.label, true)}')
    expect(modes).toContain('var(--hh-control)')
    expect(modes).toContain('var(--event-accent')
    expect(modes).toContain('var(--hh-expressive')
    expect(modes).toContain('var(--line)')
    expect(home).toContain('data-tone={activityTone(entry.label)}')
    expect(weather).toContain('data-tone={sky}')
    expect(weather).toContain('var(--hh-radius-panel')
    expect(weather).toContain('weatherSky(view)')
  })
})
