import { describe, it, expect } from 'vitest'
import {
  newRecentActivityLog, recentActivityConnectionChanged, invalidateRecentActivity,
  beginRecentActivityRead, acceptRecentActivityRead, failRecentActivityRead,
  parseRecentActivityPage, recentActivityPresentation, recentActivityTime,
} from '../../src/lib/quietAtlas/recentActivityLog.js'
import home from '../../src/routes/quiet-atlas/home/+page.svelte?raw'

const event = (id, mode, timestamp = '2026-11-01T18:30:00') => ({ id, mode, timestamp, source: 'untrusted' })
const page = (events, total = events.length) => ({ total, events })

describe('Quiet Atlas read-only recent activity log', () => {
  it('accepts bounded known activity events but never exposes raw source or internal idle', () => {
    for (const invalid of [null, {}, page([event('x', 'working')]),
      page([event(3, 'working', 'not a date')]), page(Array(7).fill(event(1, 'working'))),
      { total: -1, events: [] }, { total: 4, events: 'bad' }]) {
      expect(parseRecentActivityPage(invalid)).toBeNull()
    }
    const result = parseRecentActivityPage(page([event(1, 'idle'), event(2, 'away'),
      event(3, 'working'), event(4, 'relax')]))
    expect(result?.items.map((e) => e.label)).toEqual(['Working', 'Relaxing'])
    expect(JSON.stringify(result)).not.toContain('untrusted')
  })

  it('interprets naive UTC and explicit offset timestamps correctly through DST fall-back', () => {
    expect(parseRecentActivityPage(page([event(1, 'gaming', '2026-11-01T01:30:00')]))?.items[0].timestamp)
      .toBe(Date.parse('2026-11-01T01:30:00Z'))
    expect(parseRecentActivityPage(page([event(1, 'gaming', '2026-11-01T01:30:00-04:00')]))?.items[0].timestamp)
      .toBe(Date.parse('2026-11-01T05:30:00Z'))
  })

  it('distinguishes valid empty history from stale/unavailable reading', () => {
    const online = recentActivityConnectionChanged(newRecentActivityLog(), true)
    const { state, ticket } = beginRecentActivityRead(online)
    const empty = acceptRecentActivityRead(state, ticket, page([]), 1000)
    expect(recentActivityPresentation(empty, 1000).status).toBe('empty')
    expect(recentActivityPresentation(empty, 92000).status).toBe('stale')
    const pending = beginRecentActivityRead(empty)
    const failed = failRecentActivityRead(pending.state, pending.ticket)
    expect(recentActivityPresentation(failed, 1500).status).toBe('unavailable')
    expect(recentActivityPresentation(failed, 1500).items).toEqual([])
  })

  it('revokes in-flight responses on reconnect and tab visibility loss', () => {
    const online = recentActivityConnectionChanged(newRecentActivityLog(), true)
    const { state, ticket } = beginRecentActivityRead(online)
    expect(beginRecentActivityRead(state).ticket).toBeNull()
    const offline = recentActivityConnectionChanged(state, false)
    expect(acceptRecentActivityRead(offline, ticket, page([event(1, 'gaming')]), 2000)).toBe(offline)
    const reconnected = recentActivityConnectionChanged(offline, true)
    const later = beginRecentActivityRead(reconnected)
    const hidden = invalidateRecentActivity(later.state)
    expect(acceptRecentActivityRead(hidden, later.ticket, page([event(2, 'relax')]), 3000)).toBe(hidden)
    expect(recentActivityPresentation(hidden, 3000).items).toEqual([])
  })

  it('shows the local calendar date along with time, with an explicit timezone caveat', () => {
    const at = Date.parse('2026-11-01T18:30:00Z')
    expect(recentActivityTime(at)).toBe(new Date(at).toLocaleString(undefined, {
      month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
    }))
    expect(home).toContain("Dates and times use this device's timezone")
  })

  it('uses a bounded read-only event endpoint on the separate Home review', () => {
    expect(home).toContain("fetch('/api/events/activity?days=1&limit=6&offset=0'")
    expect(home).toContain('signal: requestController.signal')
    expect(home).toContain('cache: \'no-store\'')
    expect(home).toContain('Recent recorded activities')
    expect(home).toContain('Event history, not confirmation of a person')
    expect(home).toContain('invalidateRecentActivity(activityLog)')
    expect(home).toContain('aria-labelledby="recent-log-title"')
    expect(home).toContain('max-width:700px')
    expect(home).not.toMatch(/\b(apiPost|apiPut|setLight|activateScene|hueWrite)\s*\(/)
    expect(home).toContain('SPATIAL PLACEHOLDER · NOT A FLOOR PLAN')
  })
})
