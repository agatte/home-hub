import { describe, expect, it } from 'vitest'

import {
  activityLabel,
  automationSourceLabel,
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

  it('distinguishes explicit user override intent from autonomous couch context', () => {
    const couchState = automationStateFromStatus({
      current_mode: 'relax',
      mode_source: 'manual',
      house_state: 'home',
      activity: 'relax',
      manual_override: true,
      override_source: 'physical_context_relax',
      override_user_owned: false,
    })
    expect(couchState).toMatchObject({
      manual_override: true,
      override_source: 'physical_context_relax',
      override_user_owned: false,
    })
    expect(automationSourceLabel(couchState)).toBe('Auto (Couch context)')

    const userState = automationStateFromStatus({
      current_mode: 'relax',
      mode_source: 'manual',
      house_state: 'home',
      activity: 'relax',
      manual_override: true,
      override_source: 'api:127.0.0.1',
      override_user_owned: true,
    })
    expect(automationSourceLabel(userState)).toBe('Manual override')
  })

  it('never presents current autonomous latch owners as manual intent', () => {
    const autonomousSources = [
      'late_night_rescue',
      'ambient_relax',
      'physical_context_relax',
      'zone_posture_rule',
      'watching_sleep_guard',
      'behavioral_predictor',
      'fusion_can_override',
      'fusion_auto_apply',
      'gameday:auto',
      'gameday:auto:pregame',
      'internal',
    ]

    for (const overrideSource of autonomousSources) {
      const label = automationSourceLabel({
        ...initialAutomationState,
        manual_override: true,
        override_source: overrideSource,
        override_user_owned: false,
      })
      expect(label).toMatch(/^Auto \(/)
      expect(label).not.toBe('Manual override')
    }
  })

  it('projects stale idle activity to General only while Home', () => {
    expect(normalizeActivity('idle', 'home')).toBe('general')
    expect(normalizeActivity('idle', 'away')).toBeNull()
    expect(normalizeActivity('idle', 'sleeping')).toBeNull()
    expect(activityLabel('idle')).toBeNull()
    expect(automationStateFromStatus({ house_state: 'home', activity: 'idle' }).activity).toBe('general')
    expect(automationStateFromStatus({ house_state: 'sleeping', activity: 'idle' }).activity).toBeNull()
  })

  it('suppresses contradictory Activity while Away or Sleeping', () => {
    expect(automationStateFromStatus({ house_state: 'away', activity: 'gaming' }).activity).toBeNull()
    expect(automationStateFromStatus({ house_state: 'sleeping', activity: 'working' }).activity).toBeNull()
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

  it('clears stale Activity when a live update moves the house to an inactive state', () => {
    const prev = {
      ...initialAutomationState,
      house_state: 'home',
      activity: 'watching',
    }

    expect(mergeAutomationUpdate(prev, { house_state: 'sleeping' })).toMatchObject({
      house_state: 'sleeping',
      activity: null,
    })
    expect(mergeAutomationUpdate(prev, { house_state: 'away', activity: 'gaming' })).toMatchObject({
      house_state: 'away',
      activity: null,
    })
  })
})
