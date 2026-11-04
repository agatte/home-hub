// @vitest-environment jsdom
// #431 focused interaction regression: a real mounted Svelte component,
// not only source-string assertions or a compiler smoke test.
import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte'
import { tick } from 'svelte'
import Review from '../../src/routes/quiet-atlas/music/artist-review/+page.svelte'

afterEach(() => cleanup())

describe('#431 fictional artist-review focus and dialog ownership', () => {
  it('moves focus to the new step after every action that replaces its button', async () => {
    render(Review)
    const find = screen.getByRole('button', { name: 'Find matches' })
    find.focus()
    await fireEvent.click(find)
    await tick()
    expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Before we search.' }))

    await fireEvent.click(screen.getByRole('button', { name: 'Show fictional matches' }))
    await tick()
    expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Which one is the right match?' }))

    await fireEvent.click(screen.getByRole('radio'))
    await fireEvent.click(screen.getByRole('button', { name: 'Confirm fictional match' }))
    await tick()
    expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Match selected.' }))

    await fireEvent.click(screen.getByRole('button', { name: 'Undo this match' }))
    await tick()
    expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Which one is the right match?' }))

    await fireEvent.click(screen.getByRole('button', { name: /None look right/ }))
    await tick()
    expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Left unresolved.' }))

    await fireEvent.click(screen.getByRole('button', { name: 'Continue to next artist' }))
    await tick()
    expect(screen.getByRole('heading', { name: 'Fictional Pattern Unit' })).toBeTruthy()
    expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Find the right artist.' }))

    await fireEvent.click(screen.getByRole('button', { name: /^Previous artist$/ }))
    await tick()
    expect(screen.getByRole('heading', { name: 'Imaginary Atlas Ensemble' })).toBeTruthy()
    expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Left unresolved.' }))

    await fireEvent.click(screen.getByRole('button', { name: 'Start over' }))
    await tick()
    expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Find the right artist.' }))
    expect(screen.getByText(/0 of 4 matched in this fictional session/)).toBeTruthy()
  })

  it('does not cancel consent when a modal dialog owns Escape', async () => {
    render(Review)
    await fireEvent.click(screen.getByRole('button', { name: 'Find matches' }))
    const modal = document.createElement('section')
    modal.setAttribute('role', 'dialog')
    modal.setAttribute('aria-modal', 'true')
    document.body.appendChild(modal)
    try {
      await fireEvent.keyDown(window, { key: 'Escape' })
      await tick()
      expect(screen.getByRole('heading', { name: 'Before we search.' })).toBeTruthy()
    } finally {
      modal.remove()
    }
    await fireEvent.keyDown(window, { key: 'Escape' })
    await tick()
    expect(screen.getByRole('heading', { name: 'Find the right artist.' })).toBeTruthy()
    expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Find the right artist.' }))
  })
})
