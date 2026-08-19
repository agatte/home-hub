import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/svelte'

import ActivityOverrideControl from '$lib/components/ActivityOverrideControl.svelte'
import { automation, initialAutomationState } from '$lib/stores/automation.js'

beforeEach(() => {
  automation.set({
    ...initialAutomationState,
    mode: 'gaming',
    source: 'process',
    house_state: 'home',
    activity: 'gaming',
    manual_override: false,
  })
})

afterEach(() => {
  automation.set(initialAutomationState)
})

describe('ActivityOverrideControl', () => {
  it('distinguishes detected Gaming from a manual Gaming override', async () => {
    render(ActivityOverrideControl)

    expect(screen.getByText('Auto · Gaming')).toBeInTheDocument()

    await fireEvent.click(screen.getByRole('button', { name: /change/i }))

    const auto = screen.getByRole('button', { name: /auto use context/i })
    const gaming = screen.getByRole('button', { name: /gaming manual override/i })

    expect(auto).toHaveAttribute('aria-pressed', 'true')
    expect(gaming).toHaveAttribute('aria-pressed', 'false')
  })

  it('marks the selected manual mode only when a manual override is active', async () => {
    automation.set({
      ...initialAutomationState,
      mode: 'gaming',
      source: 'api:test',
      house_state: 'home',
      activity: 'gaming',
      manual_override: true,
    })

    render(ActivityOverrideControl)

    expect(screen.getByText('Manual · Gaming')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /return to auto/i })).toBeInTheDocument()

    await fireEvent.click(screen.getByRole('button', { name: /change/i }))

    const auto = screen.getByRole('button', { name: /auto use context/i })
    const gaming = screen.getByRole('button', { name: /gaming manual override/i })

    expect(auto).toHaveAttribute('aria-pressed', 'false')
    expect(gaming).toHaveAttribute('aria-pressed', 'true')
  })

  it('keeps every legacy Home action reachable without horizontal scrolling', async () => {
    render(ActivityOverrideControl)

    expect(screen.getByRole('button', { name: /all off/i })).toBeInTheDocument()
    await fireEvent.click(screen.getByRole('button', { name: /change/i }))

    for (const name of ['Auto', 'Gaming', 'Working', 'Watching', 'Cooking', 'Relax', 'Social', 'Sleep']) {
      expect(screen.getByRole('button', { name: new RegExp(name, 'i') })).toBeInTheDocument()
    }
  })
})
