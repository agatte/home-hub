import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/svelte'
import { tick } from 'svelte'

import ModeIndicator from '$lib/components/ModeIndicator.svelte'
import { automation, initialAutomationState } from '$lib/stores/automation.js'

beforeEach(() => {
  automation.set({
    ...initialAutomationState,
    house_state: 'home',
    activity: 'general',
  })
})

afterEach(() => {
  automation.set(initialAutomationState)
})

describe('ModeIndicator', () => {
  it('renders House State and Activity as the primary user-facing state', () => {
    render(ModeIndicator)
    expect(screen.getByText('Home')).toBeInTheDocument()
    expect(screen.getByText('General')).toBeInTheDocument()
  })

  it('updates when the shared automation state changes', async () => {
    render(ModeIndicator)
    automation.update((prev) => ({
      ...prev,
      house_state: 'winding_down',
      activity: 'relax',
    }))
    await tick()

    expect(screen.getByText('Winding Down')).toBeInTheDocument()
    expect(screen.getByText('Relax')).toBeInTheDocument()
  })

  it('does not present legacy idle as a user-facing Activity', () => {
    automation.set({
      ...initialAutomationState,
      house_state: 'home',
      activity: 'general',
      mode: 'idle',
    })
    render(ModeIndicator)

    expect(screen.queryByText('Idle')).not.toBeInTheDocument()
    expect(screen.getByText('General')).toBeInTheDocument()
  })
})
