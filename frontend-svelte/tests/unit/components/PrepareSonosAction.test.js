import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte'
import PrepareSonosAction from '$lib/components/PrepareSonosAction.svelte'
import { apiGet, apiPost } from '$lib/api.js'

vi.mock('$lib/api.js', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
}))

beforeEach(() => {
  vi.mocked(apiGet).mockImplementation((path) => Promise.resolve(
    path === '/api/host/status'
      ? { mode: 'HOME', can_control: true }
      : { status: 'preview', token: 'opaque-single-use-token', expires_in: 45, track: 'The Poplar Tree' },
  ))
  vi.mocked(apiPost).mockResolvedValue({
    status: 'ready', reason: 'unloaded_verified_play_requires_separate_action',
  })
})

afterEach(() => vi.clearAllMocks())

async function revealPreview() {
  const check = screen.queryByRole('button', { name: 'Check preparation access' })
  if (check) await fireEvent.click(check)
  return screen.findByRole('button', { name: 'Preview / manually recheck' })
}

describe('PrepareSonosAction', () => {
  it('does not preview or actuate on mount and requires two explicit clicks', async () => {
    render(PrepareSonosAction)
    const preview = await revealPreview()
    expect(apiGet).toHaveBeenCalledWith('/api/host/status')
    expect(apiGet).not.toHaveBeenCalledWith('/api/music/prepare/preview')
    expect(apiPost).not.toHaveBeenCalled()

    await fireEvent.click(preview)
    const confirm = await screen.findByRole('button', { name: 'Confirm: discard current track' })
    expect(screen.getByText(/Loaded track: The Poplar Tree/)).toBeInTheDocument()
    expect(apiPost).not.toHaveBeenCalled()

    await fireEvent.click(confirm)
    expect(await screen.findByText(/Sonos unloaded and ready/)).toBeInTheDocument()
    expect(apiPost).toHaveBeenCalledTimes(1)
    expect(apiPost).toHaveBeenCalledWith('/api/music/prepare/confirm', {
      token: 'opaque-single-use-token',
    })
    expect(screen.queryByRole('button', { name: 'Start approved track' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Confirm: discard current track' })).not.toBeInTheDocument()
  })

  it('never exposes preparation in a browser without kiosk authority', async () => {
    vi.mocked(apiGet).mockResolvedValue({ mode: 'HOME', can_control: false })
    render(PrepareSonosAction)
    const access = screen.queryByRole('button', { name: 'Check preparation access' })
    if (access) await fireEvent.click(access)
    await waitFor(() => expect(apiGet).toHaveBeenCalledWith('/api/host/status'))
    expect(screen.queryByRole('button', { name: 'Preview / manually recheck' })).not.toBeInTheDocument()
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('shows preview refusals but never exposes confirmation or sends a write', async () => {
    vi.mocked(apiGet).mockImplementation((path) => Promise.resolve(
      path === '/api/host/status'
        ? { mode: 'HOME', can_control: true }
        : { status: 'refused', reason: 'source_not_eligible' },
    ))
    render(PrepareSonosAction)
    await fireEvent.click(await revealPreview())
    expect(await screen.findByText(/This source is not eligible for preparation/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Confirm: discard current track' })).not.toBeInTheDocument()
    expect(apiPost).not.toHaveBeenCalled()
  })

  it.each([
    ['dnd_active', /Do Not Disturb is active/],
    ['apartment_away', /apartment Away/],
    ['sleeping_active', /HomeHub is Sleeping/],
    ['audio_ownership_busy', /Another audio action owns the speaker/],
    ['source_stopped_but_loaded', /Sonos is stopped but still has a source loaded/],
    ['source_evidence_unavailable', /Sonos source evidence is unavailable/],
    ['source_queue_evidence_unavailable', /Sonos queue could not be verified/],
    ['source_queue_not_empty', /Sonos queue is not empty/],
    ['source_unsupported_transport', /source is not supported for preparation/],
    ['source_playing', /Sonos is playing/],
    ['source_missing_track_details', /no verified track details/],
    ['source_not_coordinator', /group follower/],
    ['source_play_mode_not_normal', /repeat or shuffle/],
    ['source_muted', /Sonos is muted/],
    ['source_volume_zero', /Sonos volume is zero/],
    ['private-source://must-not-display', /current source or house policy/],
    ['__proto__', /current source or house policy/],
  ])('explains %s without confirmation or writes', async (reason, message) => {
    vi.mocked(apiGet).mockImplementation((path) => Promise.resolve(
      path === '/api/host/status'
        ? { can_control: true }
        : { status: 'refused', reason, track: 'private-title', uri: 'private-uri' },
    ))
    render(PrepareSonosAction)
    await fireEvent.click(await revealPreview())
    expect(await screen.findByText(message)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Confirm: discard current track' })).not.toBeInTheDocument()
    expect(screen.queryByText(/private-title|private-uri|must-not-display/)).not.toBeInTheDocument()
    if (reason === 'source_stopped_but_loaded') {
      expect(screen.getByRole('status')).toHaveTextContent('Nothing was automatically unloaded')
      expect(screen.getByRole('status')).toHaveTextContent('paused-source preparation is unavailable')
      expect(screen.getByRole('status').textContent).not.toMatch(/start|resume/i)
    }
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('keeps the already unloaded message without confirmation or writes', async () => {
    vi.mocked(apiGet).mockImplementation((path) => Promise.resolve(
      path === '/api/host/status' ? { can_control: true }
        : { status: 'ready', reason: 'already_unloaded_play_requires_separate_action' },
    ))
    render(PrepareSonosAction)
    await fireEvent.click(await revealPreview())
    expect(await screen.findByText(/Sonos is already unloaded/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Confirm: discard current track' })).not.toBeInTheDocument()
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('can cancel a preview without sending a write', async () => {
    render(PrepareSonosAction)
    await fireEvent.click(await revealPreview())
    await fireEvent.click(await screen.findByRole('button', { name: 'Cancel preparation' }))
    expect(await screen.findByText(/Preparation canceled/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Confirm: discard current track' })).not.toBeInTheDocument()
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('consumes the token on an ambiguous response without automatic retry', async () => {
    vi.mocked(apiPost).mockRejectedValue(new Error('response lost'))
    render(PrepareSonosAction)
    await fireEvent.click(await revealPreview())
    await fireEvent.click(await screen.findByRole('button', { name: 'Confirm: discard current track' }))
    expect(await screen.findByText(/Preparation outcome unknown/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Confirm: discard current track' })).not.toBeInTheDocument()
    expect(apiPost).toHaveBeenCalledTimes(1)
  })
})
