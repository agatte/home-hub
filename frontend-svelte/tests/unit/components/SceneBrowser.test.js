import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/svelte'
import { apiGet, apiPost } from '$lib/api.js'
import { activateScene } from '$lib/stores/init.js'
import SceneBrowser from '$lib/components/SceneBrowser.svelte'

vi.mock('$lib/api.js', () => ({
  apiGet: vi.fn(), apiPost: vi.fn(), apiPut: vi.fn(), apiDelete: vi.fn(),
}))
vi.mock('$lib/stores/init.js', () => ({ activateScene: vi.fn() }))

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(apiGet).mockImplementation((url) => Promise.resolve(
    url === '/api/scenes' ? { scenes: [] } : { effects: [] }
  ))
})

describe('SceneBrowser provenance and fetch states', () => {
  it('shows loading instead of empty results while each request is pending', async () => {
    vi.mocked(apiGet).mockReturnValue(new Promise(() => {}))
    render(SceneBrowser)
    expect(screen.getByText('Loading scenes…')).toBeInTheDocument()
    expect(screen.queryByText(/No scenes returned/)).not.toBeInTheDocument()
    await fireEvent.click(screen.getByRole('button', { name: 'Effects' }))
    expect(screen.getByText('Loading effects…')).toBeInTheDocument()
    expect(screen.queryByText('No effects returned')).not.toBeInTheDocument()
  })

  it('labels provenance, preserves bridge grouping and uses existing activation paths', async () => {
    vi.mocked(apiGet).mockResolvedValue({ scenes: [
      { id: 'relax', name: 'Relax', display_name: 'Relax', source: 'preset', category: 'cozy' },
      { id: 'custom_1', name: 'Mine', display_name: 'Mine', source: 'custom', category: 'custom' },
      { id: 'bridge-a', name: 'Dusk', source: 'bridge', status: 'active' },
      { id: 'bridge-b', name: 'Dusk', source: 'bridge', status: 'inactive' },
    ], effects: [] })
    render(SceneBrowser)
    await screen.findByText('HomeHub preset')
    expect(screen.getByText('HomeHub custom')).toBeInTheDocument()
    expect(apiPost).not.toHaveBeenCalled()
    expect(activateScene).not.toHaveBeenCalled()
    await fireEvent.click(screen.getByRole('button', { name: 'Relax HomeHub preset' }))
    expect(apiPost).toHaveBeenCalledWith('/api/scenes/relax/activate', {})
    await fireEvent.click(screen.getByRole('button', { name: 'Hue Scenes' }))
    expect(screen.getByText(/Freshness and bridge reachability are unknown/)).toBeInTheDocument()
    expect(screen.getAllByText('Dusk')).toHaveLength(1)
    await fireEvent.click(screen.getByRole('button', { name: 'Dusk Hue bridge' }))
    expect(vi.mocked(activateScene).mock.calls).toEqual([['bridge-a'], ['bridge-b']])
  })

  it('reports a scene request failure and recovers through a read-only retry', async () => {
    vi.mocked(apiGet).mockRejectedValueOnce(new Error('offline'))
    render(SceneBrowser)
    await screen.findByRole('alert')
    expect(screen.queryByText(/No scenes returned/)).not.toBeInTheDocument()
    await fireEvent.click(screen.getByRole('button', { name: 'Retry scenes' }))
    await screen.findByText('No scenes returned for this category')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('treats malformed effects as a fetch failure without inferring bridge connectivity', async () => {
    vi.mocked(apiGet).mockImplementation((url) => Promise.resolve(
      url === '/api/scenes' ? { scenes: [] } : {}
    ))
    render(SceneBrowser)
    await fireEvent.click(screen.getByRole('button', { name: 'Effects' }))
    await screen.findByRole('alert')
    expect(screen.queryByText(/not connected/)).not.toBeInTheDocument()
    expect(screen.queryByText('No effects returned')).not.toBeInTheDocument()
    vi.mocked(apiGet).mockResolvedValue({ effects: [] })
    await fireEvent.click(screen.getByRole('button', { name: 'Retry effects' }))
    await screen.findByText('No effects returned')
  })
})
