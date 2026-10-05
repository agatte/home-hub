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

  it('keeps Network errors visible without offering the retired admin proxy', async () => {
    vi.mocked(apiGet).mockRejectedValue(new Error('pihole stats unavailable'))
    const { container } = render(PiholeCard)

    expect(await screen.findByText('Pi-hole unavailable')).toBeInTheDocument()
    expect(screen.queryByText('Open Admin')).not.toBeInTheDocument()
    expect(container.querySelector('iframe')).toBeNull()
  })

  it('still shows typed Pi-hole stats without an admin launcher', async () => {
    vi.mocked(apiGet).mockResolvedValue({ pihole: {
      percent_blocked: 25, total_queries: 1200, blocked: 300,
      domains_on_blocklist: 1000000, active_clients: 4,
    } })
    const { container } = render(PiholeCard)

    expect(await screen.findByText('25%')).toBeInTheDocument()
    expect(screen.getByText('1.2K')).toBeInTheDocument()
    expect(apiGet).toHaveBeenCalledWith('/api/pihole/stats')
    expect(screen.queryByText('Open Admin')).not.toBeInTheDocument()
    expect(container.querySelector('iframe')).toBeNull()
  })
})
