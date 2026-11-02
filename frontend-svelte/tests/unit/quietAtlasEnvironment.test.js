import { describe, expect, it } from 'vitest'
import { compile } from 'svelte/compiler'
import page from '../../src/routes/quiet-atlas/home/+page.svelte?raw'
import component from '../../src/lib/components/QuietAtlasEnvironment.svelte?raw'
import {
  validateWeatherReport, newWeatherSnapshot, weatherConnectionChanged,
  beginWeatherRead, acceptWeatherRead, failWeatherRead, invalidateWeatherRead,
  weatherPresentation, WEATHER_REPORT_MAX_AGE_MS,
} from '../../src/lib/quietAtlas/weatherSnapshot.js'

const good = { status: 'ok', weather: { temp: 47, feels_like: 42, city: 'Indianapolis', description: 'Mostly cloudy' } }

describe('Quiet Atlas Home environment report', () => {
  it('validates actual NWS-backed REST envelope without implying source observation freshness', () => {
    expect(validateWeatherReport(good)).toEqual({ temp: 47, feelsLike: 42, city: 'Indianapolis', description: 'Mostly cloudy' })
    for (const body of [
      null, {}, { weather: good.weather }, { status: 'ok' },
      { status: 'ok', weather: { ...good.weather, temp: '47' } },
      { status: 'ok', weather: { ...good.weather, temp: Number.NaN } },
      { status: 'ok', weather: { ...good.weather, temp: 999 } },
      { status: 'ok', weather: { ...good.weather, description: '' } },
      { status: 'ok', weather: { ...good.weather, city: '' } },
    ]) expect(validateWeatherReport(body)).toBeNull()
    expect(component).toContain('cached conditions may be older')
    expect(component).toContain('Not a live indoor comfort or lighting signal.')
  })

  it('rejects stale, disconnected, failed, invalid and late report responses', () => {
    const offline = newWeatherSnapshot()
    expect(weatherPresentation(offline, 0).status).toBe('disconnected')
    const online = weatherConnectionChanged(offline, true)
    const { state, ticket } = beginWeatherRead(online)
    expect(weatherPresentation(state, 0).status).toBe('loading')
    expect(beginWeatherRead(state).ticket).toBeNull()
    const fresh = acceptWeatherRead(state, ticket, good, 1000)
    expect(weatherPresentation(fresh, 1001)).toMatchObject({ status: 'recent', report: { temp: 47 } })
    expect(weatherPresentation(fresh, 1000 + WEATHER_REPORT_MAX_AGE_MS + 1)).toMatchObject({ status: 'stale', report: null })
    const disconnected = weatherConnectionChanged(state, false)
    expect(acceptWeatherRead(disconnected, ticket, good, 1001)).toBe(disconnected)
    expect(weatherPresentation(disconnected, 1001).report).toBeNull()
    const hidden = invalidateWeatherRead(state)
    expect(acceptWeatherRead(hidden, ticket, good, 1001)).toBe(hidden)
    expect(weatherPresentation(hidden, 1001).report).toBeNull()
    const failed = failWeatherRead(state, ticket)
    expect(weatherPresentation(failed, 1001).status).toBe('unavailable')
    const invalid = acceptWeatherRead(state, ticket, { status: 'ok', weather: {} }, 1001)
    expect(weatherPresentation(invalid, 1001).report).toBeNull()
  })

  it('compiles a read-only, accessible band below lighting and before activity on Home', () => {
    expect(page).toContain('import QuietAtlasEnvironment')
    expect(page.indexOf('<QuietAtlasEnvironment />')).toBeGreaterThan(page.indexOf('class="lighting-dock"'))
    expect(page.indexOf('<QuietAtlasEnvironment />')).toBeLessThan(page.indexOf('class="recent-log"'))
    expect(component).toContain("fetch('/api/weather'")
    expect(component).toContain("cache: 'no-store'")
    expect(component).toContain('new AbortController()')
    expect(component).toContain('invalidateWeatherRead(snapshot)')
    expect(component).toContain('document.visibilityState')
    expect(component).toContain('aria-labelledby="weather-band-title"')
    expect(component).not.toMatch(/\b(apiPost|apiPut|activateScene|setLight|hueWrite)\s*\(/)
    const compiled = compile(component, { filename: 'QuietAtlasEnvironment.svelte', generate: 'dom', css: 'external' })
    expect(compiled.warnings).toEqual([])
  })
})
