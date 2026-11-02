import { describe, expect, it } from 'vitest'
import homeRoute from '../../src/routes/quiet-atlas/home/+page.svelte?raw'

describe('Quiet Atlas opt-in Home composition contract', () => {
  it('separates qualified live REST context from illustrative design examples', () => {
    expect(homeRoute).toContain('Read-only review · context is HomeHub-reported; examples are illustrative')
    expect(homeRoute).toContain('HOUSE STATE')
    expect(homeRoute).toContain('ACTIVITY')
    expect(homeRoute).toContain('{contextDisplay.house}')
    expect(homeRoute).toContain('{contextDisplay.activity}')
    expect(homeRoute).toContain('DESIGN EXAMPLES')
    expect(homeRoute).toContain('HOMEHUB CONTEXT')
    expect(homeRoute).toContain('let reviewExamples = false')
    expect(homeRoute).toContain("{#if contextDisplay.status === 'recent'}")
    expect(homeRoute).toContain('Current context not verified')
    expect(homeRoute).toContain('RECENT REST REPORT')
    expect(homeRoute).toContain('REST response is not sensor freshness or room-location evidence')
    expect(homeRoute).toContain('aria-pressed={reviewExamples}')
    expect(homeRoute).toContain('SPATIAL PLACEHOLDER · NOT A FLOOR PLAN')
  })

  it('keeps lighting groups and scene browsing discoverable', () => {
    for (const group of ['Living', 'Bedroom', 'Kitchen', 'Plant']) {
      expect(homeRoute).toContain("name: '" + group + "'")
    }
    expect(homeRoute).toContain('href="/quiet-atlas/control"') // overview entry
    expect(homeRoute).toContain('href={controlGroupHref(group.id)}')
    expect(homeRoute).toContain('href={CONTROL_SCENES_HREF}')
    expect(homeRoute).toContain('href="/quiet-atlas"') // explicit legacy preview permalink
    expect(homeRoute).toContain('Browse scenes')
    expect(homeRoute).toContain('L2 · L5')
    expect(homeRoute).toContain('L3 · L4')
  })

  it('keeps Apartment separate and introduces no light/scene writer', () => {
    expect(homeRoute).toContain('href="/"')
    expect(homeRoute).toContain('Apartment Canvas (#192)')
    expect(homeRoute).not.toMatch(/\b(apiPost|setLight|activateScene|setScene|hueWrite)\s*\(/)
    expect(homeRoute).toContain("fetch('/api/automation/status'")
  })

  it('supports multiple illustrative states and accessible review modes', () => {
    for (const state of ['unavailable', 'stale', 'empty', 'attention']) {
      expect(homeRoute).toContain(state + ': {')
    }
    expect(homeRoute).toContain("{reviewExamples ? 'Return to HomeHub report' : 'Review illustrative states'}")
    expect(homeRoute).toContain('min-height:44px')
    expect(homeRoute).toContain('prefers-reduced-motion:reduce')
    expect(homeRoute).toContain(':focus-visible')
    expect(homeRoute).toContain('max-width:700px')
    expect(homeRoute).toContain('max-width:360px')
  })
})
