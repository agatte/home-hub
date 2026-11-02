import { describe, expect, it } from 'vitest'
import { compile } from 'svelte/compiler'
import route from '../../src/routes/quiet-atlas/insights/+page.svelte?raw'
import readout from '../../src/lib/components/InsightsContextReadout.svelte?raw'
import shell from '../../src/lib/components/QuietAtlasShell.svelte?raw'
import {
  activeQuietAtlasSection, shouldShowGlobalErrorToast, shouldUseQuietAtlasShell,
} from '../../src/lib/quietAtlas/navigation.js'
import {
  newRecentActivityLog, recentActivityConnectionChanged, beginRecentActivityRead,
  acceptRecentActivityRead, recentActivityPresentation,
} from '../../src/lib/quietAtlas/recentActivityLog.js'
import {
  newHomeContextSnapshot, homeContextConnectionChanged, beginHomeContextRead,
  acceptHomeContextRead, failHomeContextRead, invalidateHomeContextRead,
  homeContextPresentation,
} from '../../src/lib/quietAtlas/homeContextSnapshot.js'

describe('Quiet Atlas opt-in Insights archetype', () => {
  it('is its own read-only route and preserves functional Analytics', () => {
    expect(shell).toContain("id: 'insights', label: 'Insights', href: '/quiet-atlas/insights'")
    expect(activeQuietAtlasSection('/quiet-atlas/insights')).toBe('insights')
    expect(activeQuietAtlasSection('/quiet-atlas/home')).toBe('home')
    expect(activeQuietAtlasSection('/analytics')).toBe('insights')
    expect(shouldUseQuietAtlasShell('/quiet-atlas/insights', new URLSearchParams())).toBe(true)
    expect(shouldShowGlobalErrorToast('/quiet-atlas/insights', new URLSearchParams())).toBe(false)
    expect(route).toContain('href="/analytics?shell=quiet-atlas"')
    expect(route).toContain('href="/quiet-atlas/home"')
    expect(route).toContain('DESIGN STUDY · NOT A LIVE FUSION OR DECISION TRACE')
  })

  it('does not reconstruct or invent confidence, outcomes or person location', () => {
    expect(route).toContain('What was observed?')
    expect(route).toContain('Why that state?')
    expect(route).toContain('What actually changed?')
    expect(route).toContain('not source-qualified in this preview')
    expect(route).toContain('Neither report reconstructs sensor inputs')
    expect(route).toContain('not confirmation of a person, room, current House State')
    expect(route).not.toMatch(/\b(apiPost|apiPut|activateScene|setLight|hueWrite)\s*\(/)
  })

  it('reads only bounded recorded events and revokes late, disconnected replies', () => {
    expect(route).toContain("fetch('/api/events/activity?days=1&limit=6&offset=0'")
    expect(route).toContain("cache: 'no-store'")
    expect(route).toContain('new AbortController()')
    expect(route).toContain('invalidateRecentActivity(activityLog)')
    expect(route).toContain('document.visibilityState')
    expect(route).toContain('window.clearInterval(ageTimer)')
    expect(route).toContain('window.clearInterval(pollTimer)')

    const online = recentActivityConnectionChanged(newRecentActivityLog(), true)
    const { state, ticket } = beginRecentActivityRead(online)
    const recent = acceptRecentActivityRead(state, ticket, {
      total: 2,
      events: [
        { id: 1, timestamp: '2026-11-01T21:00:00Z', mode: 'working' },
        { id: 2, timestamp: '2026-11-01T20:00:00Z', mode: 'idle' },
      ],
    }, 1000)
    expect(recentActivityPresentation(recent, 1500).items).toHaveLength(1)
    expect(recentActivityPresentation(recent, 92000).items).toEqual([])
    expect(recentActivityPresentation(recentActivityConnectionChanged(recent, false), 1500).items).toEqual([])
  })

  it('compiles as a responsive accessible source-first review', () => {
    const compiled = compile(route, { filename: 'InsightsPage.svelte', generate: 'dom', css: 'external' })
    expect(compiled.warnings).toEqual([])
    for (const literal of [
      'aria-labelledby="record-title"', 'aria-labelledby="mechanism-title"',
      'aria-label="Recent recorded activities"', 'role="status"',
      '@media(max-width:880px)', '@media(max-width:480px)',
      'prefers-reduced-motion:reduce', 'Dates and times use this device',
    ]) expect(route).toContain(literal)
  })
})

describe('Quiet Atlas Insights source-qualified current context', () => {
  it('reuses guarded Home context without claiming room or automation causation', () => {
    expect(route).toContain('InsightsContextReadout')
    expect(readout).toContain("fetch('/api/automation/status'")
    expect(readout).toContain("cache: 'no-store'")
    expect(readout).toContain('homeContextPresentation(snapshot, nowMs)')
    expect(readout).toContain('invalidateHomeContextRead(snapshot)')
    expect(readout).toContain('REST receipt is not source-sensor freshness')
    expect(readout).toContain('CONTEXT NOT VERIFIED')
    expect(readout).not.toMatch(/\b(apiPost|apiPut|activateScene|setLight|hueWrite)\s*\(/)
    expect(compile(readout, { filename: 'InsightsContextReadout.svelte', generate: 'dom', css: 'external' }).warnings).toEqual([])
  })

  it('only shows valid recent reports, revokes disconnect/late replies, never projects stale state', () => {
    const online = homeContextConnectionChanged(newHomeContextSnapshot(), true)
    const { state, ticket } = beginHomeContextRead(online)
    const valid = { house_state: 'home', activity: 'working' }
    const fresh = acceptHomeContextRead(state, ticket, valid, 1000)
    expect(homeContextPresentation(fresh, 1001)).toMatchObject({
      status: 'recent', house: 'Home', activity: 'Working',
    })
    expect(homeContextPresentation(fresh, 46002)).toMatchObject({
      status: 'stale', house: 'Unverified', activity: 'Unverified',
    })
    const disconnected = homeContextConnectionChanged(state, false)
    expect(acceptHomeContextRead(disconnected, ticket, valid, 2000)).toBe(disconnected)
    expect(homeContextPresentation(disconnected, 2000).status).toBe('disconnected')
    const invisible = invalidateHomeContextRead(state)
    expect(acceptHomeContextRead(invisible, ticket, valid, 2000)).toBe(invisible)
    const failure = failHomeContextRead(state, ticket)
    expect(homeContextPresentation(failure, 2000).status).toBe('unavailable')
    const invalid = acceptHomeContextRead(state, ticket, { house_state: 'home' }, 2000)
    expect(homeContextPresentation(invalid, 2000).status).toBe('unavailable')
  })
})
