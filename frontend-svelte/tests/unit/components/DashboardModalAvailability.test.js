import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/svelte'
import { apiGet } from '$lib/api.js'

import PlantWidget from '$lib/components/PlantWidget.svelte'
import PiholeCard from '$lib/components/PiholeCard.svelte'

vi.mock('$lib/api.js', () => ({
  apiGet: vi.fn(),
}))

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('dashboard modal availability', () => {
  it('opens Plants even when its status refresh fails', async () => {
    vi.mocked(apiGet).mockRejectedValue(new Error('plant status unavailable'))
    const { component } = render(PlantWidget, { cardClickable: true })

    await component.openModal()

    expect(screen.getByTitle('Plant Care App')).toBeInTheDocument()
  })

  it('opens Network even when its stats refresh fails', async () => {
    vi.mocked(apiGet).mockRejectedValue(new Error('pihole stats unavailable'))
    const { component } = render(PiholeCard, { cardClickable: true })

    await component.openModal()

    expect(screen.getByTitle('Pi-hole Admin')).toBeInTheDocument()
  })
})
