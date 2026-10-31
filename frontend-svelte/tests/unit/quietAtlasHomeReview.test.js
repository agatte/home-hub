import { describe, expect, it } from 'vitest'
import homeRoute from '../../src/routes/quiet-atlas/home/+page.svelte?raw'

describe('Quiet Atlas opt-in Home composition contract', () => {
  it('labels illustrative state rather than claiming live home readings', () => {
    expect(homeRoute).toContain('Illustrative design preview · not live HomeHub state')
    expect(homeRoute).toContain('HOUSE STATE')
    expect(homeRoute).toContain('ACTIVITY')
    expect(homeRoute).toContain('Not connected')
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
    expect(homeRoute).not.toMatch(/\bfetch\s*\(/)
  })

  it('supports multiple illustrative states and accessible review modes', () => {
    for (const state of ['unavailable', 'stale', 'empty', 'attention']) {
      expect(homeRoute).toContain(state + ': {')
    }
    expect(homeRoute).toContain('prefers-reduced-motion:reduce')
    expect(homeRoute).toContain(':focus-visible')
    expect(homeRoute).toContain('max-width:700px')
    expect(homeRoute).toContain('max-width:360px')
  })
})
