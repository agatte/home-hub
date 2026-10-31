import { describe, expect, it } from 'vitest'
import {
  newHomeContextSnapshot, homeContextConnectionChanged, invalidateHomeContextRead,
  beginHomeContextRead, acceptHomeContextRead, failHomeContextRead,
  validateHomeContextResponse, homeContextStatus, homeContextPresentation,
} from '../../src/lib/quietAtlas/homeContextSnapshot.js'
import route from '../../src/routes/quiet-atlas/home/+page.svelte?raw'

/** @param {unknown} [house_state] @param {unknown} [activity] */
const valid = (house_state = 'home', activity = 'general') => ({ house_state, activity })

function reading(body = valid(), at = 1000) {
  const online = homeContextConnectionChanged(newHomeContextSnapshot(), true)
  const { state, ticket } = beginHomeContextRead(online)
  return { state: acceptHomeContextRead(state, ticket, body, at), ticket }
}

describe('Quiet Atlas read-only HomeHub context source', () => {
  it('rejects invented, malformed, missing, or unsupported REST state', () => {
    for (const value of [
      null, [], '', { house_state: 'home' }, { activity: 'working' },
      valid('absent', 'working'), valid('home', 'fake_room'),
      valid('home', 5), valid('home', {}), valid('idle', 'general'),
    ]) {
      expect(validateHomeContextResponse(value)).toBeNull()
    }
    expect(validateHomeContextResponse(valid('home', 'working'))).toEqual({
      houseState: 'Home', activity: 'Working',
    })
    expect(validateHomeContextResponse(valid('winding_down', null))).toEqual({
      houseState: 'Winding Down', activity: null,
    })
  })

  it('normalizes internal idle and suppresses Activity while Away or Sleeping', () => {
    expect(validateHomeContextResponse(valid('home', 'idle'))).toEqual({
      houseState: 'Home', activity: 'General',
    })
    expect(validateHomeContextResponse(valid('away', 'working'))).toEqual({
      houseState: 'Away', activity: null,
    })
    expect(validateHomeContextResponse(valid('sleeping', 'gaming'))).toEqual({
      houseState: 'Sleeping', activity: null,
    })
    expect(validateHomeContextResponse(valid('winding_down', 'idle'))?.activity).toBeNull()
  })

  it('starts disconnected then loads and accepts only recent, validated REST', () => {
    const initial = newHomeContextSnapshot()
    expect(homeContextStatus(initial, 0)).toBe('disconnected')
    const online = homeContextConnectionChanged(initial, true)
    expect(homeContextStatus(online, 100)).toBe('unverified')
    const { state: fetching, ticket } = beginHomeContextRead(online)
    expect(homeContextStatus(fetching, 100)).toBe('loading')
    expect(beginHomeContextRead(fetching).ticket).toBeNull()
    const confirmed = acceptHomeContextRead(fetching, ticket, valid('home', 'working'), 1000)
    expect(homeContextStatus(confirmed, 1000)).toBe('recent')
    expect(homeContextPresentation(confirmed, 1500)).toMatchObject({
      house: 'Home', activity: 'Working', status: 'recent',
    })
    expect(homeContextPresentation(confirmed, 1500).note).toContain('not a sensor timestamp')
    expect(homeContextStatus(confirmed, 46001)).toBe('stale')
    expect(homeContextPresentation(confirmed, 46001).house).toBe('Unverified')
    expect(homeContextStatus(confirmed, 500)).toBe('stale') // clock rollback
  })

  it('does not render invalid replies as live context', () => {
    const online = homeContextConnectionChanged(newHomeContextSnapshot(), true)
    const { state, ticket } = beginHomeContextRead(online)
    const invalid = acceptHomeContextRead(state, ticket, { house_state: 'home' }, 2000)
    expect(homeContextStatus(invalid, 2000)).toBe('unavailable')
    expect(homeContextPresentation(invalid, 2000).house).toBe('Unavailable')
    const negativeTime = acceptHomeContextRead(state, ticket, valid(), -1)
    expect(homeContextStatus(negativeTime, 2000)).toBe('unavailable')
    const failed = failHomeContextRead(state, ticket)
    expect(homeContextStatus(failed, 2000)).toBe('unavailable')
  })

  it('ignores late replies after disconnect, rejoin, or tab suspension', () => {
    const online = homeContextConnectionChanged(newHomeContextSnapshot(), true)
    const { state, ticket } = beginHomeContextRead(online)
    const offline = homeContextConnectionChanged(state, false)
    expect(homeContextStatus(offline, 2000)).toBe('disconnected')
    expect(acceptHomeContextRead(offline, ticket, valid(), 2000)).toBe(offline)
    const rejoined = homeContextConnectionChanged(offline, true)
    expect(homeContextStatus(rejoined, 2000)).toBe('unverified')
    expect(failHomeContextRead(rejoined, ticket)).toBe(rejoined)
    const { state: readingAgain, ticket: nextTicket } = beginHomeContextRead(rejoined)
    expect(nextTicket?.generation).not.toBe(ticket?.generation)
    const hidden = invalidateHomeContextRead(readingAgain)
    expect(acceptHomeContextRead(hidden, nextTicket, valid(), 3000)).toBe(hidden)
    expect(homeContextStatus(hidden, 3000)).toBe('unverified')
  })

  it('does not present an older report as current on failed refetch', () => {
    const { state: recent } = reading(valid('home', 'gaming'), 1000)
    const { state: pending, ticket } = beginHomeContextRead(recent)
    const failed = failHomeContextRead(pending, ticket)
    expect(homeContextStatus(failed, 2000)).toBe('stale')
    expect(homeContextPresentation(failed, 2000).house).toBe('Unverified')
    expect(failed.reported?.houseState).toBe('Home')
    expect(homeContextStatus(homeContextConnectionChanged(recent, false), 2000)).toBe('disconnected')
  })

  it('wires only GET source into opt-in Home, without lighting commands or fabricated room data', () => {
    expect(route).toContain("fetch('/api/automation/status'")
    expect(route).toContain('cache: \'no-store\'')
    expect(route).toContain('new AbortController()')
    expect(route).toContain('homeContextPresentation(contextSnapshot, contextNowMs)')
    expect(route).toContain('Illustrative context examples')
    expect(route).not.toMatch(/\b(apiPost|apiPut|setLight|activateScene|hueWrite)\s*\(/)
    expect(route).toContain('SPATIAL PLACEHOLDER · NOT A FLOOR PLAN')
    expect(route).toContain('prefers-reduced-motion:reduce')
  })
})
