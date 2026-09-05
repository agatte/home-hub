import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/svelte'

import ActionableWidget from '$lib/components/ActionableWidget.svelte'

describe('ActionableWidget', () => {
  it('activates from the whole card surface', async () => {
    const onActivate = vi.fn()
    render(ActionableWidget, {
      ariaLabel: 'Open card',
      onActivate,
    })

    const card = screen.getByRole('button', { name: 'Open card' })
    const content = document.createElement('span')
    content.textContent = 'Card content'
    card.appendChild(content)

    await fireEvent.click(content)

    expect(onActivate).toHaveBeenCalledTimes(1)
  })

  it('supports Enter and Space keyboard activation', async () => {
    const onActivate = vi.fn()
    render(ActionableWidget, {
      ariaLabel: 'Open card',
      onActivate,
    })

    const card = screen.getByRole('button', { name: 'Open card' })
    await fireEvent.keyDown(card, { key: 'Enter' })
    await fireEvent.keyDown(card, { key: ' ' })

    expect(onActivate).toHaveBeenCalledTimes(2)
  })

  it('does not hijack nested interactive controls', async () => {
    const onActivate = vi.fn()
    render(ActionableWidget, {
      ariaLabel: 'Open card',
      onActivate,
    })

    const card = screen.getByRole('button', { name: 'Open card' })
    const nested = document.createElement('button')
    nested.textContent = 'Nested control'
    card.appendChild(nested)

    await fireEvent.click(nested)

    expect(onActivate).not.toHaveBeenCalled()
  })
})
