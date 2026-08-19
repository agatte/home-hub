import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/svelte'

import HomeContextHeader from '$lib/components/HomeContextHeader.svelte'
import { automation, initialAutomationState } from '$lib/stores/automation.js'
import { connected, deviceStatus } from '$lib/stores/connection.js'

beforeEach(() => {
  automation.set({
    ...initialAutomationState,
    mode: 'gaming',
    source: 'process',
    house_state: 'home',
    activity: 'gaming',
    time_period: 'day',
  })
  connected.set(true)
  deviceStatus.set({ hue: true, sonos: true })
})

afterEach(() => {
  automation.set(initialAutomationState)
  connected.set(false)
  deviceStatus.set({ hue: false, sonos: false })
})

describe('HomeContextHeader', () => {
  it('presents House State, Activity, and friendly automatic provenance', () => {
    render(HomeContextHeader)

    expect(screen.getByText('Home')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Gaming' })).toBeInTheDocument()
    expect(screen.getByText('Automatic · PC activity')).toBeInTheDocument()
    expect(screen.queryByText(/PROCESS/)).not.toBeInTheDocument()
    expect(screen.getByText('All systems online')).toBeInTheDocument()
  })

  it('uses manual override wording without exposing the raw source', () => {
    automation.set({
      ...initialAutomationState,
      mode: 'relax',
      source: 'api:test',
      house_state: 'home',
      activity: 'relax',
      manual_override: true,
    })

    render(HomeContextHeader)

    expect(screen.getByText('Manual override')).toBeInTheDocument()
    expect(screen.queryByText(/api:test/i)).not.toBeInTheDocument()
  })

  it('surfaces degraded system attention when a dependency is unavailable', () => {
    deviceStatus.set({ hue: false, sonos: true })

    render(HomeContextHeader)

    expect(screen.getByText('Hue is unavailable')).toBeInTheDocument()
  })
})
