import { describe, expect, it } from 'vitest'

import {
  activityLabel,
  automationStateFromStatus,
  houseStateLabel,
  initialAutomationState,
  mergeAutomationUpdate,
  normalizeActivity,
} from '$lib/stores/automation.js'

describe('automation state contract', () => {
  it('retains House State, Activity, and time period from REST status', () => {
    const state = automationStateFromStatus({
      current_mode: 'gaming',
      mode_source: 'process',
      house_state: 'home',
      activity: 'gaming',
      time_period: 'evening',
      manual_override: false,
      dnd_enabled: true,
      dnd_expiry_utc: '2026-08-19T02:00:00Z',
      dnd_minutes_remaining: 42,
    })

    expect(state).toMatchObject({
      mode: 'gaming',
      source: 'process',
      house_state: 'home',
      activity: 'gaming',
      time_period: 'evening',
      manual_override: false,
    })
    expect(state.dnd).toEqual({
      enabled: true,
      expiry_utc: '2026-08-19T02:00:00Z',
      minutes_remaining: 42,
    })
  })

  it('projects stale idle activity to General instead of exposing Idle', () => {
    expect(normalizeActivity('idle')).toBe('general')
    expect(activityLabel('idle')).toBe('General')
    expect(automationStateFromStatus({ activity: 'idle' }).activity).toBe('general')
  })

  it('formats accepted lifecycle labels and future values safely', () => {
    expect(houseStateLabel('winding_down')).toBe('Winding Down')
    expect(activityLabel('getting_ready')).toBe('Getting Ready')
  })

  it('merges live mode updates without dropping retained state', () => {
    const prev = {
      ...initialAutomationState,
      mode: 'working',
      source: 'process',
      house_state: 'home',
      activity: 'working',
      time_period: 'day',
      dnd: { enabled: true, expiry_utc: null, minutes_remaining: 10 },
    }

    const next = mergeAutomationUpdate(prev, {
      mode: 'relax',
      source: 'ambient',
      house_state: 'winding_down',
      activity: 'relax',
      time_period: 'night',
    })

    expect(next).toMatchObject({
      mode: 'relax',
      source: 'ambient',
      house_state: 'winding_down',
      activity: 'relax',
      time_period: 'night',
    })
    expect(next.dnd).toEqual(prev.dnd)
  })

  it('preserves fields omitted by a partial live update', () => {
    const prev = {
      ...initialAutomationState,
      house_state: 'home',
      activity: 'watching',
      time_period: 'evening',
    }

    expect(mergeAutomationUpdate(prev, { manual_override: true })).toMatchObject({
      house_state: 'home',
      activity: 'watching',
      time_period: 'evening',
      manual_override: true,
    })
  })
})
