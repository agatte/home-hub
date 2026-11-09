import { describe, expect, it } from 'vitest'
import homeRoute from '../../src/routes/quiet-atlas/home/+page.svelte?raw'
import insightsRoute from '../../src/routes/quiet-atlas/insights/+page.svelte?raw'
import reveal from '../../src/lib/components/QuietAtlasHomeLightingReveal.svelte?raw'

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
    expect(homeRoute).not.toContain('lightingDetailHref')
    expect(homeRoute.match(/aria-expanded=\{selectedRoom === group.id\}/g)).toHaveLength(2)
    expect(homeRoute.match(/<QuietAtlasHomeLightingReveal /g)).toHaveLength(2)
    expect(homeRoute).toContain('href={CONTROL_SCENES_HREF}')
    expect(homeRoute).toContain('href="/quiet-atlas"') // explicit legacy preview permalink
    expect(homeRoute).toContain('Browse scenes')
    expect(homeRoute).toContain('L2 · L5')
    expect(homeRoute).toContain('L3 · L4')
  })

  it('keeps atmosphere drafts local, labelled and motion optional', () => {
    expect(reveal).toContain('Design preview only — no light changes')
    expect(reveal).toContain('not a device reading')
    expect(reveal).toContain('<section class="shelf" aria-labelledby=')
    expect(reveal).toContain('aria-describedby=')
    expect(reveal).toContain('aria-pressed={draft.mood === mood}')
    expect(reveal).toContain('aria-pressed={draft.on}')
    expect(reveal).toContain("on:click={() => update({ on: !draft.on })}")
    expect(reveal).toContain("{draft.on ? 'Preview on' : 'Preview off'}")
    expect(reveal).toContain('draft.on ? draft.brightness / 100 : 0')
    expect(reveal).toContain('type="range"')
    expect(reveal).toContain('prefers-reduced-motion:reduce')
    expect(reveal).toContain('animation:none')
    expect(reveal).toContain('transition:none')
    expect(reveal).not.toMatch(/fetch\(|apiPost|apiPut|goto\(|pushState|role="dialog"|aria-modal/)
    expect(homeRoute).toContain('selectedRoom === id ? null : id')
    expect(homeRoute).toContain("event.key !== 'Escape'")
    expect(homeRoute).toContain('event.defaultPrevented')
    expect(homeRoute).toContain('const focused = document.activeElement')
    expect(homeRoute).toContain('focused !== trigger && !reveal?.contains(focused)')
    expect(homeRoute).toContain('trigger?.focus()')
    expect(homeRoute).toContain('bind:drafts={lightingDrafts}')
    expect(homeRoute).not.toMatch(/goto\(|pushState|role="dialog"|aria-modal/)
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

  it('routes all Home Insights entry points to the redesigned opt-in review', () => {
    // Desktop source rail, recent activity section, and mobile summary agree.
    expect(homeRoute.match(/href="\/quiet-atlas\/insights"/g)).toHaveLength(3)
    expect(homeRoute).not.toContain('href="/analytics?shell=quiet-atlas"')
    expect(homeRoute).toContain('View Insights')
    expect(homeRoute).toContain('Open Insights')
    // Advanced tools are still one clearly labeled link away from Insights.
    expect(insightsRoute).toContain('href="/analytics?shell=quiet-atlas"')
    expect(insightsRoute).toContain('href="/quiet-atlas/home"')
  })
})
