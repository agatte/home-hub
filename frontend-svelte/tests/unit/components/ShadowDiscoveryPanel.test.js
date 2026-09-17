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

const liveStatusPayload = {
  status: 'active', consumer: 'gaming', semantic_request: 'valheim',
  semantic_reason: 'trusted foreground game: valheim',
  shadow: true, actuation_allowed: false,
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
      catalog_verified: true,
      playback_capability: 'metadata_only',
      playback_adapter: null,
      playback_reference: null,
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
  vi.mocked(apiGet).mockImplementation((url) => Promise.resolve(
    String(url).includes('/live-context/status') ? liveStatusPayload : statusPayload
  ))
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

    expect(apiGet).toHaveBeenCalledTimes(2)
    expect(apiGet).toHaveBeenCalledWith('/api/music/discovery/status')
    expect(apiGet).toHaveBeenCalledWith('/api/music/live-context/status')
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
    await fireEvent.click(screen.getByRole('button', { name: 'Preview manual' }))
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
    expect(screen.getByText('Catalog verified · metadata only')).toBeInTheDocument()
  })

  it('persists deliberate evaluation feedback through the explicit feedback endpoint', async () => {
    const { component } = render(ShadowDiscoveryPanel)
    expect(apiPost).not.toHaveBeenCalled()
    await component.refreshStatus()
    await screen.findByText(/Last.fm source ready/)
    await fireEvent.click(screen.getByRole('button', { name: 'Preview manual' }))
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

  it('previews current trusted live context and saves feedback against it', async () => {
    vi.mocked(apiPost).mockImplementation((url) => {
      if (String(url).startsWith('/api/music/live-context/preview')) return Promise.resolve({
        status: 'shadow_ready', shadow: true, actuation_allowed: false,
        live_context: liveStatusPayload,
        discovery: { ...previewPayload, policy: 'gentle' },
      })
      if (url === '/api/music/discovery/feedback') return Promise.resolve({ status: 'ok' })
      return Promise.resolve(previewPayload)
    })
    const { component } = render(ShadowDiscoveryPanel)
    await component.refreshStatus()
    await screen.findByText(/Live: gaming/)
    await fireEvent.click(screen.getByRole('button', { name: 'Preview live context' }))
    expect(await screen.findByText('Live gaming')).toBeInTheDocument()
    const liveCall = vi.mocked(apiPost).mock.calls.find(([url]) => String(url).startsWith('/api/music/live-context/preview'))
    expect(liveCall).toBeTruthy()
    await fireEvent.click(screen.getByRole('button', { name: 'Explore' }))
    await fireEvent.click(screen.getByRole('button', { name: 'Fits me' }))
    const feedbackCall = vi.mocked(apiPost).mock.calls.find(([url]) => url === '/api/music/discovery/feedback')
    expect(feedbackCall).toBeTruthy()
    const liveFeedbackBody = /** @type {any} */ (feedbackCall?.[1])
    expect(liveFeedbackBody).toMatchObject({ mode: 'gaming', policy: 'gentle', intent: 'valheim' })
  })

  it('re-resolves live context on demand even when the page-load snapshot was inactive', async () => {
    vi.mocked(apiGet).mockImplementation((url) => Promise.resolve(
      String(url).includes('/live-context/status')
        ? { status: 'inactive', shadow: true, actuation_allowed: false }
        : statusPayload
    ))
    vi.mocked(apiPost).mockImplementation((url) => {
      if (String(url).startsWith('/api/music/live-context/preview')) return Promise.resolve({
        status: 'shadow_ready', shadow: true, actuation_allowed: false,
        live_context: liveStatusPayload,
        discovery: { ...previewPayload, policy: 'gentle' },
      })
      return Promise.resolve(previewPayload)
    })

    const { component } = render(ShadowDiscoveryPanel)
    await component.refreshStatus()
    expect(await screen.findByText('No live music context active')).toBeInTheDocument()
    const liveButton = screen.getByRole('button', { name: 'Preview live context' })
    expect(liveButton).not.toBeDisabled()
    await fireEvent.click(liveButton)
    expect(await screen.findByText('Live gaming')).toBeInTheDocument()
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
    await fireEvent.click(screen.getByRole('button', { name: 'Preview manual' }))
    const fits = await screen.findByRole('button', { name: 'Fits me' })
    await fireEvent.click(fits)
    expect(await screen.findByText(/Couldn’t save feedback/)).toBeInTheDocument()
    const firstBody = /** @type {any} */ (vi.mocked(apiPost).mock.calls[1][1])

    await fireEvent.click(fits)
    expect(await screen.findByText(/Saved .* next preview will use this/)).toBeInTheDocument()
    const secondBody = /** @type {any} */ (vi.mocked(apiPost).mock.calls[2][1])
    expect(secondBody.client_event_id).toBe(firstBody.client_event_id)
  })

  it('uses the shared request contract for Familiar and renders only verified familiar suggestions', async () => {
    vi.mocked(apiPost).mockImplementation((url) => {
      if (url === '/api/music/request/preview') return Promise.resolve({
        status: 'shadow_ready', shadow: true, actuation_allowed: false,
        resolved_request: {
          kind: 'familiar', mode: 'gaming', policy: 'gentle',
          familiarity_target: 1, novelty_target: 0, semantic_request: null,
          semantic_key: null, rationale: 'Strict familiarity request.',
        },
        familiar_suggestions: [{
          candidate: {
            provider: 'sonos_favorite', provider_id: 'fav-1', title: 'Road Trip Favorites',
            catalog_verified: true, playback_capability: 'supported', playback_capable: true,
            playback_adapter: 'sonos_favorite_title', playback_reference: 'Road Trip Favorites',
          },
          score: 0.94, taste_classification: 'proven', taste_preference: 0.8,
          reasons: ['catalog-verified, Sonos-playback-capable favorite', 'taste proven (+0.80)'],
        }],
        discovery: null,
      })
      return Promise.resolve(previewPayload)
    })
    const { component } = render(ShadowDiscoveryPanel)
    await component.refreshStatus()
    await fireEvent.click(screen.getByRole('button', { name: 'Familiar' }))
    expect(await screen.findByText('Road Trip Favorites')).toBeInTheDocument()
    expect(screen.getByText('Verified familiar favorite · Sonos-ready')).toBeInTheDocument()
    const [url, body] = vi.mocked(apiPost).mock.calls[0]
    expect(url).toBe('/api/music/request/preview')
    expect(body).toMatchObject({
      request: 'play something familiar', mode: 'gaming', count: 6, tracks_per_artist: 3,
    })
    expect(screen.queryByRole('button', { name: 'Fits me' })).not.toBeInTheDocument()
  })

  it('preserves resolved New music policy when saving discovery feedback', async () => {
    vi.mocked(apiPost).mockImplementation((url) => {
      if (url === '/api/music/request/preview') return Promise.resolve({
        status: 'shadow_ready', shadow: true, actuation_allowed: false,
        resolved_request: {
          kind: 'discovery', mode: 'gaming', policy: 'explore',
          familiarity_target: 0.2, novelty_target: 0.8, semantic_request: null,
          semantic_key: null, rationale: 'Explicit discovery request.',
        },
        familiar_suggestions: [],
        discovery: { ...previewPayload, policy: 'explore' },
      })
      if (url === '/api/music/discovery/feedback') return Promise.resolve({ status: 'ok' })
      return Promise.resolve(previewPayload)
    })
    const { component } = render(ShadowDiscoveryPanel)
    await component.refreshStatus()
    await fireEvent.click(screen.getByRole('button', { name: 'New music' }))
    const fits = await screen.findByRole('button', { name: 'Fits me' })
    await fireEvent.click(fits)
    const feedbackCall = vi.mocked(apiPost).mock.calls.find(([url]) => url === '/api/music/discovery/feedback')
    const body = /** @type {any} */ (feedbackCall?.[1])
    expect(body).toMatchObject({ mode: 'gaming', policy: 'explore', intent: null })
  })

})
