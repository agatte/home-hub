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

  it('persists deliberate evaluation feedback through the explicit feedback endpoint', async () => {
    const { component } = render(ShadowDiscoveryPanel)
    expect(apiPost).not.toHaveBeenCalled()
    await component.refreshStatus()
    await screen.findByText(/Last.fm source ready/)
    await fireEvent.click(screen.getByRole('button', { name: 'Preview recommendations' }))
    const fits = await screen.findByRole('button', { name: 'Fits me' })
    await fireEvent.click(fits)

    expect(fits.classList.contains('active')).toBe(true)
    expect(await screen.findByText(/Saved .* next preview will use this/)).toBeInTheDocument()
    expect(apiPost).toHaveBeenCalledTimes(2)
    const [url, body] = vi.mocked(apiPost).mock.calls[1]
    const feedbackBody = /** @type {any} */ (body)
    expect(url).toBe('/api/music/discovery/feedback')
    expect(feedbackBody).toMatchObject({
      action: 'fits_me',
      target_kind: 'artist',
      artist_name: 'Wardruna',
      provider: 'itunes_search',
      provider_id: '1',
      mode: 'gaming',
      policy: 'gentle',
      intent: null,
    })
    expect(feedbackBody.client_event_id).toBeTruthy()

    await fireEvent.click(fits)
    expect(apiPost).toHaveBeenCalledTimes(2)

    await fireEvent.click(screen.getByRole('button', { name: 'Interesting' }))
    expect(apiPost).toHaveBeenCalledTimes(3)
    expect(vi.mocked(apiPost).mock.calls[2][1]).toMatchObject({ action: 'interesting' })
  })

  it('reuses the same event id when retrying an uncertain feedback save', async () => {
    let feedbackCalls = 0
    vi.mocked(apiPost).mockImplementation(async (url) => {
      if (String(url).includes('/discovery/preview')) return previewPayload
      feedbackCalls += 1
      if (feedbackCalls === 1) throw new Error('response lost')
      return { status: 'ok' }
    })

    const { component } = render(ShadowDiscoveryPanel)
    await component.refreshStatus()
    await fireEvent.click(screen.getByRole('button', { name: 'Preview recommendations' }))
    const fits = await screen.findByRole('button', { name: 'Fits me' })
    await fireEvent.click(fits)
    expect(await screen.findByText(/Couldn’t save feedback/)).toBeInTheDocument()
    const firstBody = /** @type {any} */ (vi.mocked(apiPost).mock.calls[1][1])

    await fireEvent.click(fits)
    expect(await screen.findByText(/Saved .* next preview will use this/)).toBeInTheDocument()
    const secondBody = /** @type {any} */ (vi.mocked(apiPost).mock.calls[2][1])
    expect(secondBody.client_event_id).toBe(firstBody.client_event_id)
  })

})
