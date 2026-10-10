import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/svelte'
import { apiGet, apiPost } from '$lib/api.js'
import AssistedPlayAction from '$lib/components/AssistedPlayAction.svelte'
import { resetAttemptsForTests, appleMusicTrackId } from '$lib/assistedPlaybackAttempt.js'
import ApprovedAppleMusicEntry from '$lib/components/ApprovedAppleMusicEntry.svelte'

vi.mock('$lib/api.js', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
}))

const candidate = {
  provider: 'itunes_search',
  provider_id: '1713833576',
  title: 'Bang!',
  playback_capable: true,
  playback_adapter: 'sonos_apple_music_share_link',
}
const trust = { state: 'approved', playback_eligible: true, explicit_approval: true }

const fixtures = {
  '/api/host/status': { mode: 'HOME', can_control: true },
  '/api/automation/status': {
    current_mode: 'gaming', house_state: 'home', time_period: 'day', dnd_enabled: false,
  },
  '/api/sonos/status': { state: 'STOPPED', track: '', volume: 25, mute: false },
  '/api/automation/mode-volume': { gaming: { day: 25, evening: 22, night: 18 } },
  '/api/music/assisted-playback/status': {
    enabled: true, explicit_only: true, actuation_allowed: true,
  },
}

beforeEach(() => {
  vi.mocked(apiGet).mockImplementation((url) => Promise.resolve(fixtures[url]))
  vi.mocked(apiPost).mockResolvedValue({ status: 'played', reason: 'verified_stream_started' })
})

afterEach(() => {
  vi.clearAllMocks()
  resetAttemptsForTests()
  globalThis.sessionStorage.clear()
})

async function checkAccess() {
  const access = screen.queryByRole('button', { name: 'Check playback access' })
  if (access) await fireEvent.click(access)
}

async function revealPlayback() {
  await checkAccess()
  return screen.findByRole('button', { name: 'Play approved track' })
}

describe('AssistedPlayAction', () => {
  it('never actuates on mount and only exposes an explicit first step', async () => {
    render(AssistedPlayAction, { candidate, trust })
    expect(await revealPlayback()).toBeInTheDocument()
    expect(apiGet).toHaveBeenCalledWith('/api/host/status')
    expect(apiPost).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: 'Start approved track' })).not.toBeInTheDocument()
  })

  it('does not expose a play action from an ordinary LAN browser', async () => {
    vi.mocked(apiGet).mockImplementation((url) =>
      Promise.resolve(url === '/api/host/status' ? { mode: 'HOME', can_control: false } : fixtures[url])
    )
    render(AssistedPlayAction, { candidate, trust })
    await fireEvent.click(await screen.findByRole('button', { name: 'Check playback access' }))
    expect(await screen.findByText(/only on the Latitude kiosk/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Play approved track' })).not.toBeInTheDocument()
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('does not expose assisted playback for other adapters or unapproved tracks', async () => {
    const { rerender } = render(AssistedPlayAction, {
      candidate: { ...candidate, playback_adapter: 'sonos_favorite_title' },
      trust,
    })
    expect(screen.queryByRole('button', { name: 'Play approved track' })).not.toBeInTheDocument()
    await rerender({ candidate, trust: { ...trust, state: 'suggestion_only', playback_eligible: false } })
    expect(screen.queryByRole('button', { name: 'Play approved track' })).not.toBeInTheDocument()
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('blocks idle activity before any playback request is made', async () => {
    vi.mocked(apiGet).mockImplementation((url) =>
      Promise.resolve(url === '/api/automation/status'
        ? { ...fixtures[url], current_mode: 'idle' } : fixtures[url])
    )
    render(AssistedPlayAction, { candidate, trust })
    await fireEvent.click(await revealPlayback())
    expect(await screen.findByText(/unavailable in the current activity/)).toBeInTheDocument()
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('does not change volume and blocks nonmatching mode targets', async () => {
    vi.mocked(apiGet).mockImplementation((url) =>
      Promise.resolve(url === '/api/sonos/status'
        ? { ...fixtures[url], volume: 30 } : fixtures[url])
    )
    render(AssistedPlayAction, { candidate, trust })
    await fireEvent.click(await revealPlayback())
    expect(await screen.findByText(/already be at volume 25.*Current: 30/)).toBeInTheDocument()
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('rejects an active loaded track before presenting the final confirmation', async () => {
    vi.mocked(apiGet).mockImplementation((url) =>
      Promise.resolve(url === '/api/sonos/status'
        ? { ...fixtures[url], state: 'PAUSED_PLAYBACK', track: 'Existing song' } : fixtures[url])
    )
    render(AssistedPlayAction, { candidate, trust })
    await fireEvent.click(await revealPlayback())
    expect(await screen.findByText(/Sonos must be stopped/)).toBeInTheDocument()
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('requires confirmation, then sends one exact identity and durable event ID', async () => {
    render(AssistedPlayAction, { candidate, trust })
    await fireEvent.click(await revealPlayback())
    const start = await screen.findByRole('button', { name: 'Start approved track' })
    expect(apiPost).not.toHaveBeenCalled()
    expect(screen.getByText(/HomeHub will not change volume or clear the queue/)).toBeInTheDocument()
    await fireEvent.click(start)
    expect(await screen.findByText(/Verified playing: Bang!/)).toBeInTheDocument()
    const calls = vi.mocked(apiPost).mock.calls
    expect(calls).toHaveLength(1)
    expect(calls[0][0]).toBe('/api/music/assisted-playback')
    expect(calls[0][1]).toMatchObject({
      provider: 'itunes_search', provider_id: '1713833576',
    })
    const playBody = /** @type {{ client_event_id: string }} */ (calls[0][1])
    expect(playBody.client_event_id).toMatch(/^music-assisted-/)
    expect(calls[0][2]).toEqual({ timeout: 45000 })
    expect(screen.queryByRole('button', { name: 'Start approved track' })).not.toBeInTheDocument()
  })

  it('lets an operator cancel without sending an event', async () => {
    render(AssistedPlayAction, { candidate, trust })
    await fireEvent.click(await revealPlayback())
    await fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('button', { name: 'Start approved track' })).not.toBeInTheDocument()
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('treats a lost response as unknown and never retries with a new ID', async () => {
    vi.mocked(apiPost).mockRejectedValue(new Error('response lost'))
    render(AssistedPlayAction, { candidate, trust })
    await fireEvent.click(await revealPlayback())
    await fireEvent.click(await screen.findByRole('button', { name: 'Start approved track' }))
    expect(await screen.findByText(/Playback outcome unknown/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Start approved track' })).not.toBeInTheDocument()
    expect(apiPost).toHaveBeenCalledTimes(1)
  })
})

describe('exact Apple Music kiosk entry and one-attempt fencing', () => {
  it('accepts numeric IDs or exact apple.com song identities, not foreign links', () => {
    expect(appleMusicTrackId('1713833576')).toBe('1713833576')
    expect(appleMusicTrackId('https://music.apple.com/us/album/bang/1713833575?i=1713833576')).toBe('1713833576')
    expect(appleMusicTrackId('https://music.apple.com/us/song/bang/1713833576')).toBe('1713833576')
    expect(appleMusicTrackId('https://music.apple.com/us/album/bang/1713833575')).toBeNull()
    expect(appleMusicTrackId('https://music.apple.com.evil.test/us/song/bang/1713833576')).toBeNull()
    expect(appleMusicTrackId('javascript:alert(1)')).toBeNull()
    expect(appleMusicTrackId('bad')).toBeNull()
  })

  it('makes the exact-track launcher usable even without a familiar suggestion', async () => {
    render(ApprovedAppleMusicEntry)
    expect(apiPost).not.toHaveBeenCalled()
    await fireEvent.input(screen.getByLabelText('Apple Music song link or track ID'), {
      target: { value: 'https://music.apple.com/us/album/bang/1713833575?i=1713833576' },
    })
    await fireEvent.click(await revealPlayback())
    expect(await screen.findByRole('button', { name: 'Start approved track' })).toBeInTheDocument()
    expect(screen.getByText(/HomeHub will verify approval/)).toBeInTheDocument()
    await fireEvent.click(screen.getByRole('button', { name: 'Start approved track' }))
    expect(await screen.findByText(/Verified playing/)).toBeInTheDocument()
    expect(apiPost).toHaveBeenCalledTimes(1)
    expect(vi.mocked(apiPost).mock.calls[0][1]).toMatchObject({
      provider: 'itunes_search', provider_id: '1713833576',
    })
  })

  it('preserves a lost-response event fence across remounts and previews', async () => {
    vi.mocked(apiPost).mockRejectedValue(new Error('lost after accepted append'))
    const first = render(AssistedPlayAction, { candidate, trust })
    await fireEvent.click(await revealPlayback())
    await fireEvent.click(await screen.findByRole('button', { name: 'Start approved track' }))
    expect(await screen.findByText(/Playback outcome unknown/)).toBeInTheDocument()
    const sentBody = /** @type {{ client_event_id: string }} */ (vi.mocked(apiPost).mock.calls[0][1])
    const sentId = sentBody.client_event_id
    first.unmount()

    render(AssistedPlayAction, { candidate, trust })
    await checkAccess()
    expect(await screen.findByText(/Playback outcome unknown/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Play approved track' })).not.toBeInTheDocument()
    expect(apiPost).toHaveBeenCalledTimes(1)
    expect(globalThis.sessionStorage.getItem('homehub:assisted-play:v1:itunes_search:1713833576')).toContain(sentId)
  })

  it('does not repeat a completed attempt across remounts without another explicit check', async () => {
    const first = render(AssistedPlayAction, { candidate, trust })
    await fireEvent.click(await revealPlayback())
    await fireEvent.click(await screen.findByRole('button', { name: 'Start approved track' }))
    expect(await screen.findByText(/Verified playing/)).toBeInTheDocument()
    first.unmount()

    render(AssistedPlayAction, { candidate, trust })
    await checkAccess()
    expect(await screen.findByText(/Verified playing/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Check before another attempt' })).toBeInTheDocument()
    expect(apiPost).toHaveBeenCalledTimes(1)
  })

  it('refuses an unapproved exact identity without client-provided trust authority', async () => {
    vi.mocked(apiPost).mockResolvedValue({
      status: 'suppressed', reason: 'trust_not_playback_eligible',
    })
    render(ApprovedAppleMusicEntry)
    await fireEvent.input(screen.getByLabelText('Apple Music song link or track ID'), {
      target: { value: '1713833576' },
    })
    await fireEvent.click(await revealPlayback())
    await fireEvent.click(await screen.findByRole('button', { name: 'Start approved track' }))
    expect(await screen.findByText(/trust_not_playback_eligible/)).toBeInTheDocument()
    expect(vi.mocked(apiPost).mock.calls[0][1]).not.toHaveProperty('trust')
  })
})

describe('exact-identity approval action', () => {
  it('approves without playback, then requires a distinct explicit confirmation', async () => {
    vi.mocked(apiPost).mockImplementation((url) => Promise.resolve(
      url === '/api/music/trust/approval'
        ? { trust: { state: 'approved', playback_eligible: true } }
        : { status: 'played' }
    ))
    render(ApprovedAppleMusicEntry)
    await fireEvent.input(screen.getByLabelText('Apple Music song link or track ID'), {
      target: { value: '1713833576' },
    })
    await fireEvent.click(await screen.findByRole('button', { name: 'Check approval access' }))
    await fireEvent.click(await screen.findByRole('button', { name: 'Approve this exact track' }))
    expect(await screen.findByText(/Exact track approval saved/)).toBeInTheDocument()
    expect(apiPost).toHaveBeenCalledTimes(1)
    expect(vi.mocked(apiPost).mock.calls[0][0]).toBe('/api/music/trust/approval')
    expect(vi.mocked(apiPost).mock.calls[0][1]).toMatchObject({
      action: 'approve', provider: 'itunes_search', provider_id: '1713833576',
    })
    expect(vi.mocked(apiPost).mock.calls[0][1]).not.toHaveProperty('trust')
    expect(screen.queryByRole('button', { name: 'Start approved track' })).not.toBeInTheDocument()
    await fireEvent.click(await revealPlayback())
    expect(await screen.findByRole('button', { name: 'Start approved track' })).toBeInTheDocument()
    expect(apiPost).toHaveBeenCalledTimes(1)
  })
})
