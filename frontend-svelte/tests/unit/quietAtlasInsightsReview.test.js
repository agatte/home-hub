import { describe, expect, it } from 'vitest'
import { compile } from 'svelte/compiler'
import route from '../../src/routes/quiet-atlas/insights/+page.svelte?raw'
import shell from '../../src/lib/components/QuietAtlasShell.svelte?raw'
import {
  activeQuietAtlasSection, shouldShowGlobalErrorToast, shouldUseQuietAtlasShell,
} from '../../src/lib/quietAtlas/navigation.js'
import {
  newRecentActivityLog, recentActivityConnectionChanged, beginRecentActivityRead,
  acceptRecentActivityRead, recentActivityPresentation,
} from '../../src/lib/quietAtlas/recentActivityLog.js'

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
    expect(route).toContain('does not reconstruct')
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
