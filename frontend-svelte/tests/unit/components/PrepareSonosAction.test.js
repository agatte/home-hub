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
    expect(await screen.findByText(/Preparation refused: source_not_eligible/)).toBeInTheDocument()
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
