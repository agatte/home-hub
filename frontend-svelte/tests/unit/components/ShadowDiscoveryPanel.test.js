import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/svelte'
import { apiGet, apiPost } from '$lib/api.js'

import ShadowDiscoveryPanel from '$lib/components/ShadowDiscoveryPanel.svelte'

vi.mock('$lib/api.js', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
}))

const statusPayload = {
  shadow: true,
  actuation_allowed: false,
  source_enabled: true,
  semantic_enabled: true,
  policies: ['gentle', 'explore'],
}

const previewPayload = {
  status: 'shadow_ready',
  shadow: true,
  actuation_allowed: false,
  policy: 'explore',
  source_cache_hit: false,
  clusters: [{
    artist_name: 'Wardruna',
    score: 0.84,
    artist_classification: 'exploratory',
    artist_depth: 0,
    novelty_ratio: 1,
    semantic_score: 0.76,
    semantic_intent: 'valheim',
    matched_semantics: ['norse', 'folk', 'epic'],
    reasons: [
      'Last.fm adjacency to Heilung (0.82)',
      'semantic valheim match 0.76 (norse, folk, epic)',
    ],
    tracks: [{
      provider: 'itunes_search',
      provider_id: '1',
      artist_name: 'Wardruna',
      track_name: 'Helvegen',
      album_name: 'Runaljod – Yggdrasil',
      artwork_url: null,
      external_url: 'https://music.apple.com/example',
      taste_classification: 'exploratory',
    }],
  }],
}

beforeEach(() => {
  vi.mocked(apiGet).mockResolvedValue(statusPayload)
  vi.mocked(apiPost).mockResolvedValue(previewPayload)
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('ShadowDiscoveryPanel', () => {
  it('checks capability but does not run discovery on mount', async () => {
    const { component } = render(ShadowDiscoveryPanel)
    expect(apiPost).not.toHaveBeenCalled()
    await component.refreshStatus()
    await screen.findByText(/Last.fm source ready/)

    expect(apiGet).toHaveBeenCalledTimes(1)
    expect(apiGet).toHaveBeenCalledWith('/api/music/discovery/status')
    expect(apiPost).not.toHaveBeenCalled()
    expect(screen.getByText('Nothing runs until you ask.')).toBeInTheDocument()
  })

  it('sends context, policy, and optional intent only after explicit preview', async () => {
    const { component } = render(ShadowDiscoveryPanel)
    expect(apiPost).not.toHaveBeenCalled()
    await component.refreshStatus()
    await screen.findByText(/Last.fm source ready/)
    await fireEvent.change(screen.getByLabelText('Discovery context'), {
      target: { value: 'gaming' },
    })
    await fireEvent.input(screen.getByPlaceholderText(/energetic, Valheim/), {
      target: { value: 'Valheim' },
    })
    await fireEvent.click(screen.getByRole('button', { name: 'Explore' }))
    await fireEvent.click(screen.getByRole('button', { name: 'Preview recommendations' }))
    expect(apiPost).toHaveBeenCalledTimes(1)
    const [url, body, options] = vi.mocked(apiPost).mock.calls[0]
    const parsed = new URL(String(url), 'http://homehub.local')
    expect(body).toBeUndefined()
    expect(options).toEqual({ timeout: 30000 })
    expect(parsed.pathname).toBe('/api/music/discovery/preview')
    expect(parsed.searchParams.get('mode')).toBe('gaming')
    expect(parsed.searchParams.get('policy')).toBe('explore')
    expect(parsed.searchParams.get('intent')).toBe('Valheim')

    expect(await screen.findByText('Wardruna')).toBeInTheDocument()
    expect(screen.getByText('76% semantic fit')).toBeInTheDocument()
    expect(screen.getByText(/matched norse, folk, epic/)).toBeInTheDocument()
    expect(screen.getByText('Helvegen')).toBeInTheDocument()
  })

  it('keeps evaluation feedback local to the current session', async () => {
    const { component } = render(ShadowDiscoveryPanel)
    expect(apiPost).not.toHaveBeenCalled()
    await component.refreshStatus()
    await screen.findByText(/Last.fm source ready/)
    await fireEvent.click(screen.getByRole('button', { name: 'Preview recommendations' }))
    const fits = await screen.findByRole('button', { name: 'Fits me' })
    await fireEvent.click(fits)

    expect(fits.classList.contains('active')).toBe(true)
    expect(screen.getByText('Not saved or learned yet')).toBeInTheDocument()
    expect(apiPost).toHaveBeenCalledTimes(1)
  })
})
