import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/svelte'
import { apiGet, apiPost } from '$lib/api.js'
import ApprovedAppleMusicEntry from '$lib/components/ApprovedAppleMusicEntry.svelte'

vi.mock('$lib/api.js', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
}))

beforeEach(() => {
  vi.mocked(apiGet).mockResolvedValue({ can_control: true })
  vi.mocked(apiPost).mockResolvedValue({ status: 'ok' })
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('ApprovedAppleMusicEntry discovery handoff', () => {
  it('prefills a reviewed exact track without creating approval or playback', async () => {
    render(ApprovedAppleMusicEntry, {
      props: { selectedTrack: { provider_id: '1713833576' } },
    })

    expect(screen.getByLabelText('Apple Music song link or track ID')).toHaveValue('1713833576')
    await fireEvent.click(screen.getByRole('button', { name: 'Check approval access' }))
    expect(await screen.findByRole('button', { name: 'Approve this exact track' })).toBeInTheDocument()
    expect(screen.getByText(/Discovery track selected/)).toBeInTheDocument()
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('accepts deliberate later selections without overwriting manual input on unchanged props', async () => {
    const { rerender } = render(ApprovedAppleMusicEntry, {
      props: { selectedTrack: { provider_id: '1713833576' } },
    })
    const input = screen.getByLabelText('Apple Music song link or track ID')
    await fireEvent.input(input, { target: { value: 'another search' } })
    expect(input).toHaveValue('another search')

    await rerender({ selectedTrack: { provider_id: '1713833576' } })
    expect(input).toHaveValue('1713833576')
    await rerender({ selectedTrack: { provider_id: '1713833576' } })
    expect(input).toHaveValue('1713833576')

    await rerender({ selectedTrack: { provider_id: '1713833577' } })
    expect(input).toHaveValue('1713833577')
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('ignores a malformed handoff and never triggers an action', async () => {
    render(ApprovedAppleMusicEntry, {
      props: { selectedTrack: { provider_id: 'not-an-apple-song' } },
    })
    expect(screen.getByLabelText('Apple Music song link or track ID')).toHaveValue('')
    expect(apiPost).not.toHaveBeenCalled()
  })
})
