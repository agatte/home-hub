import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/svelte'

import ModeCardDeck from '$lib/components/ModeCardDeck.svelte'
import { automation, initialAutomationState } from '$lib/stores/automation.js'

beforeEach(() => {
  automation.set(initialAutomationState)
})

afterEach(() => {
  automation.set(initialAutomationState)
})

describe('ModeCardDeck override provenance', () => {
  it('keeps Auto active for autonomous couch-driven Relax', () => {
    automation.set({
      ...initialAutomationState,
      mode: 'relax',
      house_state: 'home',
      activity: 'relax',
      manual_override: true,
      override_source: 'physical_context_relax',
      override_user_owned: false,
    })

    render(ModeCardDeck)

    expect(screen.getByRole('button', { name: 'Auto mode' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Relax mode' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('activates Relax only for explicit user-owned override intent', () => {
    automation.set({
      ...initialAutomationState,
      mode: 'relax',
      house_state: 'home',
      activity: 'relax',
      manual_override: true,
      override_source: 'api:test',
      override_user_owned: true,
    })

    render(ModeCardDeck)

    expect(screen.getByRole('button', { name: 'Auto mode' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByRole('button', { name: 'Relax mode' })).toHaveAttribute('aria-pressed', 'true')
  })
})
