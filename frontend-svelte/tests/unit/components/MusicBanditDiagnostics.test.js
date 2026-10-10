import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/svelte'
import { apiGet } from '$lib/api.js'
import MusicBanditDiagnostics from '$lib/components/MusicBanditDiagnostics.svelte'

vi.mock('$lib/api.js', () => ({ apiGet: vi.fn() }))

const empty = { arm_count: 0, total_selections: 0, top_arms: {} }
const snapshot = {
  arm_count: 12,
  total_selections: 8,
  // Deliberately omit arms_per_mode: it counts truncated rankings, not all arms.
  top_arms: { relax: { any: [
    { title: 'Evening playlist', period: 'evening', alpha: 9, beta: 1, mean: 0.9 },
    { title: 'Morning playlist', period: 'morning', alpha: 3, beta: 1, mean: 0.75 },
  ] } },
}

beforeEach(() => vi.resetAllMocks())

describe('MusicBanditDiagnostics', () => {
  it('shows loading before the read-only snapshot arrives', async () => {
    /** @type {(value: any) => void} */
    let resolve = (_value) => {}
    vi.mocked(apiGet).mockReturnValue(new Promise(r => { resolve = r }))
    const { component } = render(MusicBanditDiagnostics)
    void component.refresh()
    expect(screen.getByText('Loading bandit diagnostics…')).toBeInTheDocument()
    expect(screen.getByRole('button')).toBeDisabled()
    resolve(empty)
    expect(await screen.findByText(/No arm rankings reported/)).toBeInTheDocument()
  })

  it('preserves cross-period ranking and explains the evidence limits', async () => {
    vi.mocked(apiGet).mockResolvedValue(snapshot)
    const { component } = render(MusicBanditDiagnostics)
    await component.refresh()
    await screen.findByText(/stored arms/)
    await fireEvent.click(screen.getByText('Inspect rankings and model parameters'))
    const rows = within(screen.getByRole('list')).getAllByRole('listitem')
    expect(rows[0]).toHaveTextContent('Evening playlist')
    expect(rows[0]).toHaveTextContent('Period: evening · Mean: 0.9 · Alpha: 9 · Beta: 1')
    expect(rows[1]).toHaveTextContent('Morning playlist')
    expect(screen.getByText(/stored arms/)).toHaveTextContent('12 stored arms · 8 recorded selections')
    expect(screen.getByText(/Up to five arms/)).toHaveTextContent('not period-specific winners')
    expect(screen.getByText(/Alpha and beta are posterior/)).toHaveTextContent('not observed success/failure counts')
    expect(screen.getByText(/Alpha and beta are posterior/)).toHaveTextContent('cold-start status cannot be determined')
    expect(apiGet).toHaveBeenCalledExactlyOnceWith('/api/music/bandit-status')
  })

  it('does not interpret an empty response as cold start or availability', async () => {
    vi.mocked(apiGet).mockResolvedValue(empty)
    const { component } = render(MusicBanditDiagnostics)
    await component.refresh()
    expect(await screen.findByText(/cannot distinguish an unavailable bandit from an empty model/)).toBeInTheDocument()
    expect(screen.queryByText('Inspect rankings and model parameters')).not.toBeInTheDocument()
  })

  it('clears stale rankings on refresh failure and allows a read-only retry', async () => {
    vi.mocked(apiGet).mockResolvedValueOnce(snapshot)
      .mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(empty)
    const { component } = render(MusicBanditDiagnostics)
    await component.refresh()
    await screen.findByText('Evening playlist')
    await fireEvent.click(screen.getByRole('button', { name: 'Refresh diagnostics' }))
    expect(await screen.findByText(/Bandit diagnostics unavailable/)).toBeInTheDocument()
    expect(screen.queryByText('Evening playlist')).not.toBeInTheDocument()
    await fireEvent.click(screen.getByRole('button', { name: 'Refresh diagnostics' }))
    await screen.findByText(/No arm rankings reported/)
    expect(vi.mocked(apiGet).mock.calls).toEqual(Array(3).fill(['/api/music/bandit-status']))
  })
})
